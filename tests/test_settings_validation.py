"""Settings validation, at both ends of the wire.

The defect: PATCH /api/admin/settings took `dict[str, str]` and wrote any
string to any existing key. `sync_schedule` is then handed to `croniter()`
inside the sync service's scheduler_loop try block, so a malformed value raised,
the generic handler caught it, and the loop retried every POLL_INTERVAL seconds
forever -- never polling a job, never running a sync, and (since the logging
fix) logging an error on every pass. An admin who mistyped the cron box took
mirroring down, with no error anywhere near the mistake.

Three layers are exercised here, because a value can arrive by three routes:

  1. shared/settings_spec.py   the rules themselves, and the bounds
  2. backend/app/api/admin.py  the write boundary -- the value never lands
  3. sync/sync_service.py      the read boundary -- for values that landed
                               anyway, via psql, a restore, or an older deploy

Layer 3 is the one that proves the wedge is actually closed rather than merely
made harder to reach: the tests at the bottom write straight to the settings
table, bypassing the API entirely, and show the scheduler still schedules.
"""
import ast
import logging
import pathlib
from datetime import datetime

import pytest
from sqlalchemy import select

from app.api import admin as admin_module

from shared.models import Setting
from shared.settings_spec import (
    DEFAULT_SYNC_SCHEDULE,
    MAX_SYNC_BANDWIDTH_LIMIT,
    MAX_SYNC_TIMEOUT,
    MIN_SYNC_BANDWIDTH_LIMIT,
    MIN_SYNC_TIMEOUT,
    SETTING_KEYS,
    SETTING_SPECS,
    SettingError,
    UnknownSettingKey,
    canonical_setting,
    parse_setting,
    validate_settings,
)
from sync.sync_service import SyncService
from tests.conftest import auth_header

# The exact string from the brief: the value that wedged the scheduler.
WEDGE_SCHEDULE = "every 4 hours"


# ---------------------------------------------------------------------------
# Layer 1: the spec
# ---------------------------------------------------------------------------

def test_the_spec_covers_exactly_the_seeded_keys():
    """backend/app/main.py seeds from SETTING_SPECS, so this pins the set of
    keys the whole system has an opinion about. A key added to one and not the
    other is the drift this module exists to prevent."""
    assert SETTING_KEYS == {
        "sync_schedule",
        "sync_bandwidth_limit",
        "sync_timeout",
        "sync_on_startup",
    }


def test_the_sync_service_only_maps_keys_the_spec_knows():
    """SyncService._SETTING_ATTRS says which row feeds which attribute. A key
    listed there with no spec would raise UnknownSettingKey inside
    reload_settings -- and an exception escaping reload_settings lands in
    scheduler_loop's generic handler, which retries every ten seconds forever.
    That is the wedge, reintroduced from the other side."""
    assert set(SyncService._SETTING_ATTRS) <= SETTING_KEYS


def test_every_default_survives_its_own_validator():
    """A default that its own spec rejects would make a fresh deployment
    invalid from the first boot."""
    for key, spec in SETTING_SPECS.items():
        rendered = spec.render(spec.default)
        assert canonical_setting(key, rendered) == rendered, key


# --- sync_schedule ---------------------------------------------------------

VALID_SCHEDULES = [
    ("daily-at-4", "0 4 * * *"),
    ("every-five-minutes", "*/5 * * * *"),
    ("weekdays", "0 4 * * 1-5"),
    ("named-weekday", "0 4 * * MON"),
    ("six-field-with-seconds", "0 4 * * * *"),
    ("range-with-step", "0-59/2 * * * *"),
    ("nickname-daily", "@daily"),
    ("nickname-weekly", "@weekly"),
    ("last-day-of-month", "0 4 L * *"),
]

INVALID_SCHEDULES = [
    ("the-wedge", WEDGE_SCHEDULE, "prose, not cron -- the value from the incident"),
    ("empty", "", "an empty box submitted"),
    ("whitespace-only", "   ", "looks set, holds nothing"),
    ("four-fields", "* * * *", "one field short"),
    ("seven-fields", "0 4 * * * * *", "one field long"),
    ("minute-out-of-range", "60 4 * * *", "minutes are 0-59"),
    ("hour-out-of-range", "0 24 * * *", "hours are 0-23"),
    ("day-out-of-range", "0 4 32 * *", "no month has 32 days"),
    ("month-out-of-range", "0 4 * 13 *", "no thirteenth month"),
    ("weekday-out-of-range", "0 4 * * 8", "weekdays are 0-7"),
    ("zero-step", "*/0 * * * *", "step of zero is an infinite loop, not a schedule"),
    ("jenkins-hash", "H/5 * * * *", "Jenkins syntax, not cron"),
    # @reboot has no next fire time. croniter cannot advance it and this
    # scheduler has nothing to hang it on, so accepting it would mean a
    # schedule that silently never fires.
    ("reboot-nickname", "@reboot", "no next occurrence to schedule"),
]


@pytest.mark.parametrize("name,value", VALID_SCHEDULES, ids=[c[0] for c in VALID_SCHEDULES])
def test_valid_cron_expressions_are_accepted(name, value):
    assert parse_setting("sync_schedule", value) == value


@pytest.mark.parametrize(
    "name,value,why", INVALID_SCHEDULES, ids=[c[0] for c in INVALID_SCHEDULES]
)
def test_invalid_cron_expressions_are_rejected(name, value, why):
    with pytest.raises(SettingError) as exc:
        parse_setting("sync_schedule", value)
    assert "sync_schedule" in str(exc.value), (
        "the message must name the key: the admin panel shows only the pydantic "
        "`msg` field, not `loc`, so an unnamed message reads as 'something is "
        "wrong somewhere'"
    )


def test_the_wedge_value_would_have_wedged_the_scheduler():
    """The value is rejected *because* it breaks the real call, not because it
    looks odd. This asserts the failure it would have caused."""
    from croniter import CroniterBadCronError, croniter

    with pytest.raises(CroniterBadCronError):
        croniter(WEDGE_SCHEDULE, datetime(2026, 9, 1, 12, 0)).get_next(datetime)

    with pytest.raises(SettingError):
        parse_setting("sync_schedule", WEDGE_SCHEDULE)


# --- sync_timeout ----------------------------------------------------------

TIMEOUT_CASES = [
    ("one-second", "1", False, "the brief's example: parses, breaks every sync"),
    ("zero", "0", False, "rsync reads 0 as 'no timeout' -- the hang this bounds"),
    ("negative", "-1", False, "not a duration"),
    ("just-below-floor", str(MIN_SYNC_TIMEOUT - 1), False, "one below the floor"),
    ("the-floor", str(MIN_SYNC_TIMEOUT), True, "the lowest value that clears a quiet phase"),
    ("the-default", "600", True, "what main.py seeds"),
    ("the-ceiling", str(MAX_SYNC_TIMEOUT), True, "24 hours"),
    ("just-above-ceiling", str(MAX_SYNC_TIMEOUT + 1), False, "one above the ceiling"),
    ("milliseconds-typo", "600000", False, "600 seconds entered in milliseconds"),
    ("not-a-number", "60O", False, "letter O for zero -- silently ignored before"),
    ("float", "600.5", False, "rsync --timeout takes whole seconds"),
    ("empty", "", False, "an empty box submitted"),
]


@pytest.mark.parametrize(
    "name,value,ok,why", TIMEOUT_CASES, ids=[c[0] for c in TIMEOUT_CASES]
)
def test_sync_timeout_bounds(name, value, ok, why):
    if ok:
        assert parse_setting("sync_timeout", value) == int(value)
    else:
        with pytest.raises(SettingError):
            parse_setting("sync_timeout", value)


# --- sync_bandwidth_limit --------------------------------------------------

BANDWIDTH_CASES = [
    ("unlimited", "0", True, "rsync's documented 'no limit', and the seeded default"),
    ("negative", "-1", False, "not a rate"),
    ("one-kbps", "1", False,
     "job 615's 14 MB file list alone would take 4 hours to cross at 1 KB/s"),
    ("just-below-floor", str(MIN_SYNC_BANDWIDTH_LIMIT - 1), False, "one below the floor"),
    ("the-floor", str(MIN_SYNC_BANDWIDTH_LIMIT), True,
     "roughly where a limit throttles a transfer instead of killing it"),
    ("a-real-throttle", "20000", True, "20 MB/s, a plausible operator choice"),
    ("the-ceiling", str(MAX_SYNC_BANDWIDTH_LIMIT), True, "10 GB/s"),
    ("just-above-ceiling", str(MAX_SYNC_BANDWIDTH_LIMIT + 1), False, "one above the ceiling"),
    ("bytes-not-kb", "1000000000", False, "1 GB/s entered in bytes"),
    ("not-a-number", "unlimited", False, "the word, not the number"),
]


@pytest.mark.parametrize(
    "name,value,ok,why", BANDWIDTH_CASES, ids=[c[0] for c in BANDWIDTH_CASES]
)
def test_sync_bandwidth_limit_bounds(name, value, ok, why):
    if ok:
        assert parse_setting("sync_bandwidth_limit", value) == int(value)
    else:
        with pytest.raises(SettingError):
            parse_setting("sync_bandwidth_limit", value)


# --- sync_on_startup -------------------------------------------------------

ON_STARTUP_CASES = [
    ("true", "true", True),
    ("false", "false", False),
    ("upper", "TRUE", True),
    ("padded", "  false  ", False),
    ("one", "1", True),
    ("zero", "0", False),
    ("yes", "yes", True),
    ("no", "no", False),
]


@pytest.mark.parametrize("name,value,expected", ON_STARTUP_CASES,
                         ids=[c[0] for c in ON_STARTUP_CASES])
def test_sync_on_startup_accepted_spellings(name, value, expected):
    assert parse_setting("sync_on_startup", value) is expected


@pytest.mark.parametrize("value", ["ture", "tru", "", "maybe", "on/off", "2"])
def test_sync_on_startup_rejects_anything_else(value):
    """`.lower() == "true"` read every one of these as False and said nothing.
    A typo that means the opposite of what was intended is exactly the class of
    mistake a validator is for."""
    with pytest.raises(SettingError):
        parse_setting("sync_on_startup", value)


# --- canonical form --------------------------------------------------------

CANONICAL_CASES = [
    ("sync_schedule", "  0 4 * * *  ", "0 4 * * *"),
    ("sync_schedule", "0 4 * * *\n", "0 4 * * *"),
    ("sync_timeout", " 0600 ", "600"),
    ("sync_timeout", "+600", "600"),
    ("sync_bandwidth_limit", "0", "0"),
    ("sync_on_startup", "TRUE", "true"),
    ("sync_on_startup", "yes", "true"),
    ("sync_on_startup", "0", "false"),
]


@pytest.mark.parametrize("key,raw,stored", CANONICAL_CASES)
def test_stored_value_is_canonical(key, raw, stored):
    """What goes into the column is what the parser produced, not what was
    typed. The sync service compares the schedule string it read last cycle
    against the one it just read to decide whether to recompute the next run;
    without canonicalisation a stray trailing space reads as a change."""
    assert canonical_setting(key, raw) == stored


# --- batch behaviour -------------------------------------------------------

def test_a_batch_reports_every_bad_value_not_just_the_first():
    """One round trip, one complete answer. Reporting only the first means an
    operator fixes it, resubmits, and finds the next one."""
    with pytest.raises(SettingError) as exc:
        validate_settings({
            "sync_schedule": WEDGE_SCHEDULE,
            "sync_timeout": "1",
            "sync_bandwidth_limit": "0",
        })
    message = str(exc.value)
    assert "sync_schedule" in message
    assert "sync_timeout" in message
    assert "sync_bandwidth_limit" not in message, "the valid key must not be blamed"


def test_a_batch_of_valid_values_comes_back_canonical():
    assert validate_settings({
        "sync_schedule": " 0 4 * * * ",
        "sync_on_startup": "TRUE",
    }) == {"sync_schedule": "0 4 * * *", "sync_on_startup": "true"}


def test_unknown_keys_are_not_the_value_validator_s_business():
    """Whether a key exists is a database question. validate_settings passes it
    through so the route can answer it with the 404 it has always answered."""
    assert validate_settings({"not_a_setting": "anything"}) == {}
    with pytest.raises(UnknownSettingKey):
        parse_setting("not_a_setting", "anything")


# ---------------------------------------------------------------------------
# Layer 2: the API write boundary
# ---------------------------------------------------------------------------

@pytest.fixture
def settings_rows(db_session):
    """The four seeded rows, as backend/app/main.py's lifespan creates them."""
    existing = {
        s.key for s in db_session.execute(select(Setting)).scalars().all()
    }
    for key, spec in SETTING_SPECS.items():
        if key in existing:
            continue
        db_session.add(Setting(
            key=key, value=spec.render(spec.default), description=spec.description
        ))
    db_session.commit()
    return {
        s.key: s for s in db_session.execute(select(Setting)).scalars().all()
    }


def stored(db_session, key):
    return db_session.execute(
        select(Setting.value).where(Setting.key == key)
    ).scalar_one()


async def test_the_wedge_value_is_rejected_at_the_api(client, seed, settings_rows, db_session):
    """The headline: the string that hung the scheduler no longer reaches the
    database. 422, and the row is untouched."""
    before = stored(db_session, "sync_schedule")

    response = await client.patch(
        "/api/admin/settings",
        json={"settings": {"sync_schedule": WEDGE_SCHEDULE}},
        headers=auth_header(seed["users"]["admin"]),
    )

    assert response.status_code == 422, response.text
    assert stored(db_session, "sync_schedule") == before


async def test_the_rejection_message_names_the_key_and_the_value(client, seed, settings_rows):
    """admin.js renders `error.detail.map(e => e.msg)` and nothing else -- not
    `loc`. A message that does not name the key tells the operator nothing."""
    response = await client.patch(
        "/api/admin/settings",
        json={"settings": {"sync_schedule": WEDGE_SCHEDULE}},
        headers=auth_header(seed["users"]["admin"]),
    )
    messages = " ".join(item["msg"] for item in response.json()["detail"])
    assert "sync_schedule" in messages
    assert WEDGE_SCHEDULE in messages


@pytest.mark.parametrize("key,value", [
    ("sync_schedule", WEDGE_SCHEDULE),
    ("sync_timeout", "1"),
    ("sync_timeout", "0"),
    ("sync_bandwidth_limit", "-5"),
    ("sync_bandwidth_limit", "1"),
    ("sync_on_startup", "ture"),
])
async def test_unusable_values_are_rejected_at_the_api(
    client, seed, settings_rows, db_session, key, value
):
    before = stored(db_session, key)
    response = await client.patch(
        "/api/admin/settings",
        json={"settings": {key: value}},
        headers=auth_header(seed["users"]["admin"]),
    )
    assert response.status_code == 422, response.text
    assert stored(db_session, key) == before


async def test_a_valid_batch_is_applied_and_stored_canonically(
    client, seed, settings_rows, db_session
):
    response = await client.patch(
        "/api/admin/settings",
        json={"settings": {
            "sync_schedule": "  30 5 * * *  ",
            "sync_timeout": "0900",
            "sync_on_startup": "TRUE",
        }},
        headers=auth_header(seed["users"]["admin"]),
    )
    assert response.status_code == 200, response.text
    assert stored(db_session, "sync_schedule") == "30 5 * * *"
    assert stored(db_session, "sync_timeout") == "900"
    assert stored(db_session, "sync_on_startup") == "true"


async def test_an_unknown_key_still_gets_a_404(client, seed, settings_rows):
    """Behaviour preserved deliberately. Validation must not turn a missing key
    into a 422 -- the two mean different things and the panel shows both."""
    response = await client.patch(
        "/api/admin/settings",
        json={"settings": {"no_such_setting": "0 4 * * *"}},
        headers=auth_header(seed["users"]["admin"]),
    )
    assert response.status_code == 404, response.text
    assert "no_such_setting" in response.json()["detail"]


async def test_a_batch_with_an_unknown_key_applies_none_of_it(
    client, seed, settings_rows, db_session
):
    """Half a batch is worse than none of it: the operator sees an error and
    has no way to know which half landed.

    Ordering matters here -- the valid key is first, so a single-pass
    implementation would have mutated it before reaching the unknown one."""
    before = stored(db_session, "sync_schedule")

    response = await client.patch(
        "/api/admin/settings",
        json={"settings": {
            "sync_schedule": "30 5 * * *",
            "no_such_setting": "whatever",
        }},
        headers=auth_header(seed["users"]["admin"]),
    )

    assert response.status_code == 404, response.text
    assert stored(db_session, "sync_schedule") == before


async def test_a_batch_with_one_bad_value_applies_none_of_it(
    client, seed, settings_rows, db_session
):
    before_schedule = stored(db_session, "sync_schedule")
    before_timeout = stored(db_session, "sync_timeout")

    response = await client.patch(
        "/api/admin/settings",
        json={"settings": {
            "sync_schedule": "30 5 * * *",   # fine
            "sync_timeout": "1",             # not fine
        }},
        headers=auth_header(seed["users"]["admin"]),
    )

    assert response.status_code == 422, response.text
    assert stored(db_session, "sync_schedule") == before_schedule
    assert stored(db_session, "sync_timeout") == before_timeout


async def test_the_audit_log_records_the_canonical_value(client, seed, settings_rows):
    """`changes` is what the audit trail and the toast both show. It must be
    the stored value, not the typed one, or the record disagrees with the row."""
    response = await client.patch(
        "/api/admin/settings",
        json={"settings": {"sync_on_startup": "YES"}},
        headers=auth_header(seed["users"]["admin"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["changes"]["sync_on_startup"]["new"] == "true"


def test_no_setting_is_mutated_before_every_key_has_been_resolved():
    """Structural, because the behavioural test above cannot tell the
    difference -- and that is the finding, not a gap in the test.

    The single-pass version assigned `setting.value` as it went and only then
    discovered that a later key did not exist. Nothing was written, but only
    because of two things outside this function: get_db rolls back on any
    exception, and both session makers are built with autoflush=False. Change
    either -- add an autoflush, add an intermediate commit, call this from a
    caller that swallows the HTTPException -- and half a batch lands, silently.

    So the ordering is pinned here rather than left to be re-derived: every
    SELECT happens in the first loop, every assignment in the second, and the
    404 can only be raised from the first.
    """
    source = pathlib.Path(admin_module.__file__).read_text()
    tree = ast.parse(source)
    func = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "update_settings"
    )

    loops = [n for n in func.body if isinstance(n, ast.For)]
    assert len(loops) == 2, "expected a resolve loop and a write loop"
    resolve, write = loops

    def assigns_to_a_setting(node):
        return [
            ast.unparse(t)
            for stmt in ast.walk(node) if isinstance(stmt, ast.Assign)
            for t in stmt.targets
            if isinstance(t, ast.Attribute) and "setting" in ast.unparse(t.value)
        ]

    def raises(node):
        return [n for n in ast.walk(node) if isinstance(n, ast.Raise)]

    assert not assigns_to_a_setting(resolve), (
        "the loop that can raise 404 must not mutate anything: "
        f"{assigns_to_a_setting(resolve)}"
    )
    assert raises(resolve), "the 404 belongs in the resolve loop"
    assert assigns_to_a_setting(write), "the write loop must be the one that writes"
    assert not raises(write), "nothing may fail once writing has begun"


@pytest.mark.parametrize("role", ["operator", "readonly"])
async def test_authorisation_still_precedes_validation(
    client, seed, settings_rows, db_session, role
):
    """A non-admin sending an invalid value gets 403, not 422.

    Pinned because it is not obvious: FastAPI resolves dependencies and the
    request body in the same pass, and a 422 here would tell an unauthorised
    caller which keys exist and what shape they take."""
    before = stored(db_session, "sync_schedule")
    response = await client.patch(
        "/api/admin/settings",
        json={"settings": {"sync_schedule": WEDGE_SCHEDULE}},
        headers=auth_header(seed["users"][role]),
    )
    assert response.status_code == 403, response.text
    assert stored(db_session, "sync_schedule") == before


# ---------------------------------------------------------------------------
# Layer 3: the sync service's own defence
#
# Everything below writes the settings table directly, the way psql or a
# restore would. The API never sees these values. They are the answer to "what
# happens if it reaches the database by another route".
# ---------------------------------------------------------------------------

# `service` and `factory` come from tests/conftest.py. The service they build
# holds exactly the env defaults these tests start from: schedule "0 4 * * *",
# timeout 600, bandwidth limit 0.

def write_setting_directly(factory, key, value):
    """Bypass the API completely -- this is the psql path."""
    session = factory()
    try:
        row = session.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
        if row is None:
            session.add(Setting(key=key, value=value))
        else:
            row.value = value
        session.commit()
    finally:
        session.close()


async def test_reload_settings_adopts_good_values(service, factory):
    write_setting_directly(factory, "sync_schedule", "30 5 * * *")
    write_setting_directly(factory, "sync_timeout", "900")
    write_setting_directly(factory, "sync_bandwidth_limit", "20000")

    await service.reload_settings()

    assert service.sync_schedule == "30 5 * * *"
    assert service.sync_timeout == 900
    assert service.sync_bandwidth_limit == 20000
    assert isinstance(service.sync_timeout, int), "rsync --timeout is formatted from this"


async def test_a_wedge_value_in_the_database_is_refused_on_read(
    service, factory, caplog
):
    """The value got in by another route. The service declines to adopt it and
    says so -- the old code had no guard on sync_schedule at all."""
    write_setting_directly(factory, "sync_schedule", WEDGE_SCHEDULE)

    with caplog.at_level(logging.WARNING, logger="sync.sync_service"):
        await service.reload_settings()

    assert service.sync_schedule == DEFAULT_SYNC_SCHEDULE
    assert "Ignoring unusable setting" in caplog.text
    assert WEDGE_SCHEDULE in caplog.text


@pytest.mark.parametrize("key,attr,bad,previous", [
    ("sync_timeout", "sync_timeout", "60O", 600),
    ("sync_timeout", "sync_timeout", "1", 600),
    ("sync_bandwidth_limit", "sync_bandwidth_limit", "-5", 0),
    ("sync_bandwidth_limit", "sync_bandwidth_limit", "fast", 0),
])
async def test_a_bad_numeric_value_is_refused_loudly_not_silently(
    service, factory, caplog, key, attr, bad, previous
):
    """`except ValueError: pass` kept the previous value and left no trace, so
    an operator who typed a letter O saw the setting saved and never found out
    it was being ignored. Same outcome now, but with a WARNING naming the key
    and the value."""
    write_setting_directly(factory, key, bad)

    with caplog.at_level(logging.WARNING, logger="sync.sync_service"):
        await service.reload_settings()

    assert getattr(service, attr) == previous
    assert key in caplog.text
    assert bad in caplog.text


async def test_one_bad_setting_does_not_stop_the_others_loading(service, factory):
    """Per-key, not per-batch. A wedged schedule must not also cost the service
    a timeout it could have used."""
    write_setting_directly(factory, "sync_schedule", WEDGE_SCHEDULE)
    write_setting_directly(factory, "sync_timeout", "900")

    await service.reload_settings()

    assert service.sync_schedule == DEFAULT_SYNC_SCHEDULE
    assert service.sync_timeout == 900


async def test_the_scheduler_still_schedules_after_a_wedge_reaches_the_database(
    service, factory, caplog
):
    """The wedge, closed at the last layer.

    Before: croniter(self.sync_schedule, ...) was called inline in
    scheduler_loop's try block, raised, was caught by the generic handler, and
    the loop retried every ten seconds without ever polling a job or running a
    sync. This asserts the loop's very next action instead: a real next-run
    time, computed from the fallback schedule."""
    write_setting_directly(factory, "sync_schedule", WEDGE_SCHEDULE)
    await service.reload_settings()

    base = datetime(2026, 9, 1, 12, 0)
    next_run = service._next_scheduled_run(base)

    assert isinstance(next_run, datetime)
    assert next_run > base


async def test_the_scheduler_survives_a_value_that_never_passed_reload_settings(
    service, caplog
):
    """The last hole: self.sync_schedule also comes from the SYNC_SCHEDULE
    environment variable, which nothing validates. _next_scheduled_run is the
    point of use, so it is checked there too, and the fallback is recorded on
    the instance so the loop does not re-derive it every cycle."""
    service.sync_schedule = WEDGE_SCHEDULE

    with caplog.at_level(logging.ERROR, logger="sync.sync_service"):
        next_run = service._next_scheduled_run(datetime(2026, 9, 1, 12, 0))

    assert next_run == datetime(2026, 9, 2, 4, 0), "the seeded default, 04:00 daily"
    assert service.sync_schedule == DEFAULT_SYNC_SCHEDULE
    assert "Unusable sync schedule" in caplog.text


async def test_a_good_schedule_is_left_alone_by_the_fallback(service):
    service.sync_schedule = "30 5 * * *"
    # 05:30 daily; the base is 12:00, so the next occurrence is tomorrow.
    assert service._next_scheduled_run(datetime(2026, 9, 1, 12, 0)) == datetime(2026, 9, 2, 5, 30)
    assert service.sync_schedule == "30 5 * * *"
