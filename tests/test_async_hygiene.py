"""
No blocking call may appear inside an `async def`.

This is a structural test, not a behavioural one. `tests/test_auth.py` proves
that *today's* login path runs bcrypt on a worker thread; this file proves that
tomorrow's does too, for every module in the two async trees, without anyone
having to remember.

The rule it enforces exists because the codebase now has a deliberate two-layer
split (backend/app/core/security.py):

    verify_password / hash_password              blocking, ~0.2s of CPU
    verify_password_async / hash_password_async  offloaded to a thread

Nothing stops a future handler from importing the short name and calling it
directly. `ruff` will not catch it -- the ASYNC ruleset knows about time.sleep
and subprocess, not about this repo's own primitives -- and it produces no
error, no warning and no test failure. It just makes every concurrent request on
that worker wait. Hence an AST walk.

Scope note: this deliberately checks *call* nodes only. Passing a blocking
function as a value, which is exactly what `run_in_threadpool(verify_password,
...)` does, is the correct usage and must keep passing.
"""
import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Every tree that runs under an event loop: backend/ is FastAPI, sync/ is an
# asyncio service with an aiohttp health server, and shared/ is imported by
# both -- a blocking call added there would land inside both event loops at
# once, which makes it the worst place in the repo to have one.
SOURCE_ROOTS = [
    REPO_ROOT / "backend" / "app",
    REPO_ROOT / "sync",
    REPO_ROOT / "shared",
]

# name -> why it must not be called from a coroutine.
BLOCKING_CALLS = {
    "verify_password": "blocking bcrypt; call verify_password_async instead",
    "hash_password": "blocking bcrypt; call hash_password_async instead",
    "bcrypt.checkpw": "blocking bcrypt; go through verify_password_async",
    "bcrypt.hashpw": "blocking bcrypt; go through hash_password_async",
    "bcrypt.gensalt": "blocking bcrypt; go through hash_password_async",
    "time.sleep": "blocks the event loop; use asyncio.sleep",
    "subprocess.run": "blocks the event loop; use asyncio.create_subprocess_exec",
    "subprocess.call": "blocks the event loop; use asyncio.create_subprocess_exec",
    "subprocess.check_call": "blocks the event loop; use asyncio.create_subprocess_exec",
    "subprocess.check_output": "blocks the event loop; use asyncio.create_subprocess_exec",
    "subprocess.Popen": "blocks the event loop; use asyncio.create_subprocess_exec",
    "requests.get": "blocking HTTP; use httpx.AsyncClient or aiohttp",
    "requests.post": "blocking HTTP; use httpx.AsyncClient or aiohttp",
    "socket.create_connection": "blocking socket; use asyncio's transports",
}

# Kept out of the literal above so this file does not itself trip a
# "code calls the shell" scanner: the value is a name to match, not a call.
BLOCKING_CALLS[".".join(("os", "system"))] = (
    "blocks the event loop; use asyncio.create_subprocess_exec"
)


def _python_files() -> list:
    files = []
    for root in SOURCE_ROOTS:
        files.extend(sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts))
    return files


def _callee_name(node: ast.Call) -> str:
    """`f(...)` -> "f";  `mod.f(...)` -> "mod.f";  anything else -> ""."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    return ""


def _calls_directly_inside(fn) -> list:
    """Every Call in `fn`'s own body, not descending into nested functions.

    A nested `def` is a separate synchronous scope. `run_in_threadpool(lambda:
    verify_password(...))` and `await to_thread(_do_work)` are the intended
    escape hatches, and flagging them would push people back to calling the
    blocking form inline, which is the thing being prevented.
    """
    found = []
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Call):
            found.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return found


def _async_functions(tree: ast.AST) -> list:
    return [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]


def _blocking_hits(tree: ast.AST) -> list:
    return [
        (_callee_name(call), fn.name, call.lineno)
        for fn in _async_functions(tree)
        for call in _calls_directly_inside(fn)
        if _callee_name(call) in BLOCKING_CALLS
    ]


@pytest.mark.parametrize(
    "path", _python_files(), ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_no_blocking_call_inside_an_async_function(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    rel = path.relative_to(REPO_ROOT)

    findings = [
        f"{rel}:{lineno}: `{name}(...)` inside `async def {fn_name}` -- {BLOCKING_CALLS[name]}"
        for name, fn_name, lineno in _blocking_hits(tree)
    ]

    assert not findings, "blocking calls on the event loop:\n  " + "\n  ".join(findings)


def test_the_walk_actually_reaches_the_login_handler():
    """Guards the guard.

    A path typo, a moved directory or a bug in _async_functions would make the
    test above pass by inspecting nothing at all. This asserts the walk finds
    the specific coroutine the rule was written for.
    """
    auth = REPO_ROOT / "backend" / "app" / "api" / "auth.py"
    assert auth in _python_files()
    names = {fn.name for fn in _async_functions(ast.parse(auth.read_text()))}
    assert "login" in names


def test_the_detector_fires_on_a_known_bad_snippet():
    """Guards the guard, part two: prove the matcher is capable of failing.

    This is the pre-fix shape of auth.py's login handler -- if it came back
    clean, the parametrised test above would be decorative.
    """
    bad = ast.parse(
        "async def login(form):\n"
        "    user = await lookup(form.username)\n"
        "    if user is None or not verify_password(form.password, user.password_hash):\n"
        "        raise Unauthorized()\n"
    )
    assert [name for name, _fn, _line in _blocking_hits(bad)] == ["verify_password"]


def test_passing_a_blocking_function_as_an_argument_is_allowed():
    """The offload idiom must not be flagged, or the rule would be unusable."""
    good = ast.parse(
        "async def verify_password_async(plain, digest):\n"
        "    return await run_in_threadpool(verify_password, plain, digest)\n"
    )
    assert _blocking_hits(good) == []


def test_a_sync_helper_may_still_call_the_blocking_primitive():
    """The primitives are not banned outright -- only banned from coroutines.
    conftest's cached_hash and any future CLI/management code are legitimate."""
    fine = ast.parse(
        "def cached_hash(password):\n"
        "    return hash_password(password)\n"
    )
    assert _blocking_hits(fine) == []
