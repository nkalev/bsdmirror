"""Reduced motion and motion timing (spec sections 4.4 and 9's "Motion").

Every animation and transition the public site declares must be switched off
under `prefers-reduced-motion: reduce`, and no stylesheet may use the `all`
catch-all in a transition/animation shorthand -- naming every property a rule
actually animates is what lets one `*, *::before, *::after { transition: none
!important }` turn all of them off at once, and lets a reviewer see, from the
rule itself, exactly what moves.

Scope: style.css (spec sections 4.2-4.4) and error.css. A sheet needs its own
`@media (prefers-reduced-motion: reduce)` block as soon as it declares any
motion at all: a `@keyframes` rule, or any `transition` or `animation` other
than `none`. A colour fade counts -- spec section 4.4 turns "every animation
and transition" off -- so error.css's theme fade needs the block as much as
style.css's sheen does.

Colour changes must also settle inside the contrast harness's sampling
windows (spec section 4.4): a `color`, `background`, `background-color`,
`border-color`, `fill`, `stroke` or `outline-color` transition runs on
`--transition-fast` or `--transition-base`, never longer. Transforms and
shadows may take longer; the harness never measures them.

admin.css still has two real animations (`spin`, `slideIn`) and is
deliberately out of scope until the admin console's own redesign (spec
section 10: "PR 3 extends it to admin.css, whose spin and slideIn animations
stay until then").
"""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STYLE_CSS = REPO_ROOT / "frontend" / "public" / "css" / "style.css"
ERROR_CSS = REPO_ROOT / "frontend" / "public" / "css" / "error.css"
STYLESHEETS = [STYLE_CSS, ERROR_CSS]

# `all` as a whole word inside a transition/animation shorthand's value list
# -- catches `transition: all 150ms ease` and `transition: color .2s, all
# .2s` alike, not a property that merely contains "all" as a substring.
TRANSITION_ALL_RE = re.compile(r"(?:transition|animation)\s*:\s*(?:[^;]*,\s*)?all\b")
KEYFRAMES_RE = re.compile(r"@keyframes\b")
# A transition or animation shorthand and its value; the negative look-behind
# keeps `-webkit-transition` and `animation-name` out.
MOTION_RE = re.compile(r"(?<![\w-])(?:transition|animation)\s*:\s*([^;]+);")
TRANSITION_RE = re.compile(r"(?<![\w-])transition\s*:\s*([^;]+);")
REDUCED_MOTION_OPEN_RE = re.compile(r"@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)\s*\{")
# Scoped to the block find_reduced_motion_block() already extracted, so this
# never needs to worry about a brace nested inside some other rule.
ALL_SELECTOR_RE = re.compile(r"\*\s*,\s*\*::before\s*,\s*\*::after\s*\{([^}]*)\}")

# Spec section 4.4, "Settle within the harness windows": the contrast harness
# samples 250ms after a hover and 450ms after a theme switch.
COLOUR_PROPERTIES = {
    "color",
    "background",
    "background-color",
    "border-color",
    "fill",
    "stroke",
    "outline-color",
}
SETTLING_DURATIONS = {"var(--transition-fast)", "var(--transition-base)"}


def _strip_comments(css_text):
    return re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)


def _at_rule_body(css_text, open_brace_end):
    """The body of an at-rule whose opening `{` ends at `open_brace_end`,
    found by counting nested braces rather than assuming any indentation
    convention (contrast this with the column-0 trick
    test_error_pages_inline_styles.py uses for a similarly-shaped tokens.css
    lookup -- that sheet's formatting makes the shortcut safe; writing the
    general case once here means style.css's own nested rules can never
    trip it up)."""
    depth, i = 1, open_brace_end
    while depth > 0 and i < len(css_text):
        if css_text[i] == "{":
            depth += 1
        elif css_text[i] == "}":
            depth -= 1
        i += 1
    return css_text[open_brace_end : i - 1]


def find_reduced_motion_block(css_text):
    m = REDUCED_MOTION_OPEN_RE.search(css_text)
    if not m:
        return None
    return _at_rule_body(css_text, m.end())


def needs_a_reduced_motion_override(css_text):
    """True if this sheet declares any @keyframes, or any transition or
    animation other than `none` -- the reduced-motion block's own
    `transition: none !important` never counts as motion."""
    css = _strip_comments(css_text)
    if KEYFRAMES_RE.search(css):
        return True
    return any(not m.group(1).strip().startswith("none") for m in MOTION_RE.finditer(css))


def _split_top_level_commas(value):
    """A transition list's items: split on the commas between them, not on
    the ones inside a function such as cubic-bezier(.2, .8, .2, 1)."""
    items, depth, start = [], 0, 0
    for i, ch in enumerate(value):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            items.append(value[start:i])
            start = i + 1
    items.append(value[start:])
    return [" ".join(item.split()) for item in items]


def slow_colour_transitions(css_text):
    """Every transition item that animates one of COLOUR_PROPERTIES on
    anything but --transition-fast or --transition-base, as written."""
    slow = []
    for m in TRANSITION_RE.finditer(_strip_comments(css_text)):
        for item in _split_top_level_commas(m.group(1)):
            prop, _, timing = item.partition(" ")
            if prop in COLOUR_PROPERTIES and timing not in SETTLING_DURATIONS:
                slow.append(item)
    return slow


def test_no_stylesheet_uses_the_all_catch_all():
    offenders = []
    for sheet in STYLESHEETS:
        text = sheet.read_text(encoding="utf-8")
        offenders += [f"{sheet.name}: {m.group(0)!r}" for m in TRANSITION_ALL_RE.finditer(text)]
    assert offenders == [], (
        "transition/animation: all found; name every property explicitly so the "
        "reduced-motion block below can turn each one off individually:\n  "
        + "\n  ".join(offenders)
    )


def test_a_sheet_with_any_motion_turns_it_off_under_reduced_motion():
    for sheet in STYLESHEETS:
        text = sheet.read_text(encoding="utf-8")
        if not needs_a_reduced_motion_override(text):
            continue
        body = find_reduced_motion_block(text)
        assert body is not None, (
            f"{sheet.name} declares a transition, an animation or @keyframes "
            f"but has no @media (prefers-reduced-motion: reduce) block"
        )
        rule = ALL_SELECTOR_RE.search(body)
        assert rule, f"{sheet.name}'s reduced-motion block has no `*, *::before, *::after` rule"
        declarations = rule.group(1)
        assert re.search(
            r"animation\s*:\s*none\s*!important", declarations
        ), f"{sheet.name}'s reduced-motion rule does not set animation: none !important"
        assert re.search(
            r"transition\s*:\s*none\s*!important", declarations
        ), f"{sheet.name}'s reduced-motion rule does not set transition: none !important"


def test_colour_transitions_settle_within_the_harness_windows():
    slow = []
    for sheet in STYLESHEETS:
        text = sheet.read_text(encoding="utf-8")
        slow += [f"{sheet.name}: {item}" for item in slow_colour_transitions(text)]
    assert slow == [], (
        "a colour, background or border transition runs on something other than "
        "--transition-fast or --transition-base, so the contrast harness could "
        "sample it mid-fade:\n  " + "\n  ".join(slow)
    )


def test_the_predicate_can_actually_require_the_block():
    """A guard that has only ever been seen skipping is indistinguishable
    from one that can never fire."""
    assert needs_a_reduced_motion_override("@keyframes spin { to { transform: rotate(1turn); } }")
    assert needs_a_reduced_motion_override(".x { transition: all 150ms ease; }")
    assert needs_a_reduced_motion_override(".x { transition: color 150ms ease; }")
    assert needs_a_reduced_motion_override(".x { animation: spin 1s linear infinite; }")
    assert not needs_a_reduced_motion_override(".x { transition: none; }")
    assert not needs_a_reduced_motion_override(".x { color: red; }")


def test_the_all_catch_all_regex_does_not_fire_on_a_property_merely_containing_all():
    """`all` must be a whole word: a property list like `transition: background-
    color .2s` must never be mistaken for the banned catch-all merely because
    "all" appears inside "background-color"."""
    assert not TRANSITION_ALL_RE.search(".x { transition: background-color .2s ease; }")


def test_the_reduced_motion_block_extractor_can_actually_find_one():
    sample = (
        "@media (prefers-reduced-motion: reduce) {\n"
        "    html { scroll-behavior: auto; }\n\n"
        "    *, *::before, *::after {\n"
        "        animation: none !important;\n"
        "        transition: none !important;\n"
        "    }\n"
        "}\n"
        ".after-the-block { color: red; }\n"
    )
    body = find_reduced_motion_block(sample)
    assert body is not None
    assert "after-the-block" not in body, "the extractor read past the block's own closing brace"
    rule = ALL_SELECTOR_RE.search(body)
    assert rule and "animation: none !important" in rule.group(1)


def test_the_duration_check_can_actually_find_a_slow_colour_transition():
    """Same reasoning as the predicate's self-test above, for
    slow_colour_transitions(): a transform may take --transition-lift, a
    colour may not, and a comma inside cubic-bezier() does not split an
    item."""
    assert slow_colour_transitions(
        ".x { transition: color var(--transition-lift), transform var(--transition-lift); }"
    ) == ["color var(--transition-lift)"]
    assert slow_colour_transitions(
        ".x { transition: background-color 400ms cubic-bezier(.2, .8, .2, 1); }"
    ) == ["background-color 400ms cubic-bezier(.2, .8, .2, 1)"]
    assert not slow_colour_transitions(
        ".x { transition: transform var(--transition-lift), color var(--transition-fast); }"
    )
    assert not slow_colour_transitions("* { transition: none !important; }")


def test_the_checks_cover_style_css_and_error_css():
    """The checks above loop over STYLESHEETS; this pins that list to both
    files, so a typo in it cannot silently shrink every check to one."""
    assert {p.name for p in STYLESHEETS} == {"style.css", "error.css"}
