"""Pins the admin panel's tokens across PR 2's palette switch.

docs/design/2026-09-25-reflection-redesign.md's palette change (section 4.1)
rewrites the same primitive and semantic layers of tokens.css the admin panel
has always read through the cascade -- LIGHT THEME, DARK THEME, and the small
ADMIN SURFACE block on top. PR 2 rewrites the first two; the admin panel must
not move at all until PR 3 gives it its own redesign.

The fix lives in tokens.css itself, not here: a LEGACY ADMIN section inside
the [data-surface="admin"] block declares every token admin.css actually
reads at today's value, as a literal, so nothing there can resolve through a
shared layer PR 2 repoints. This file pins that fix two ways --

  1. every token admin.css uses must be declared directly in the admin
     block, not merely reachable through it, so a shared-layer change can
     never quietly reach admin again; and
  2. those declarations must equal a fixed snapshot, so the block itself can
     only change on purpose --

plus a self-check that the snapshot's key set still matches what admin.css
actually uses, so the first two claims cannot both stay green while quietly
checking the wrong set. PR 3 deletes the whole section once the admin panel
gets its own redesign.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKENS_CSS = REPO_ROOT / "frontend" / "public" / "css" / "tokens.css"
ADMIN_CSS = REPO_ROOT / "frontend" / "public" / "admin" / "css" / "admin.css"

# The 28 tokens admin.css uses (19 colours, then 9 non-colour), each at the
# value it resolves to today -- re-verified by hand against tokens.css's
# INVARIANTS, LIGHT THEME, DARK THEME and ADMIN SURFACE blocks, since the
# admin panel is permanently data-theme="dark" data-surface="admin". Colours
# are the flat, uppercase hex a browser paints, not a var() reference: that is
# what makes the pin independent of whatever changes above it in the cascade.
LEGACY_ADMIN_TOKENS = {
    "--accent-primary": "#F48C06",
    "--bg-card": "#1A1A2E",
    "--bg-primary": "#0D0D1A",
    "--bg-secondary": "#1A1A2E",
    "--bg-tertiary": "#2A2A40",
    "--border-color": "#2A2A40",
    "--status-error": "#EF4444",
    "--status-error-bg": "#462B3B",
    "--status-error-text": "#F87171",
    "--status-healthy": "#22C55E",
    "--status-healthy-bg": "#1C3C38",
    "--status-info-bg": "#203B56",
    "--status-info-text": "#38BDF8",
    "--status-syncing": "#F59E0B",
    "--status-syncing-bg": "#463427",
    "--text-muted": "#9696AC",
    "--text-on-accent": "#0D0D1A",
    "--text-primary": "#E8E8F0",
    "--text-secondary": "#A0A0B8",
    "--font-sans": "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    "--font-mono": "'JetBrains Mono', 'Fira Code', monospace",
    "--header-height": "64px",
    "--radius-lg": "14px",
    "--radius-md": "10px",
    "--radius-sm": "6px",
    "--sidebar-width": "260px",
    "--transition-base": "300ms ease",
    "--transition-fast": "150ms ease",
}

# Same tiny reader test_contrast.py uses: no nested rules ever appear inside
# tokens.css's flat custom-property blocks, so a non-greedy match between the
# outermost braces is enough -- see that file's docstring for the fuller
# parser this deliberately does not reimplement.
_RULE_RE = re.compile(r"([^{}]+)\{([^}]*)\}")


def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _admin_block() -> str:
    css = _strip_css_comments(TOKENS_CSS.read_text(encoding="utf-8"))
    bodies = [
        body for sel, body in _RULE_RE.findall(css) if sel.strip() == '[data-surface="admin"]'
    ]
    assert (
        len(bodies) == 1
    ), f'expected exactly one [data-surface="admin"] rule, found {len(bodies)}'
    return bodies[0]


def _admin_block_declarations() -> dict:
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", _admin_block()))


def _vars_used_by_admin_css() -> set:
    return set(re.findall(r"var\((--[\w-]+)\)", ADMIN_CSS.read_text(encoding="utf-8")))


def test_every_admin_css_token_is_pinned_in_the_admin_block():
    """Every var(--x) admin.css consumes must be declared directly in
    tokens.css's [data-surface="admin"] block -- not merely resolvable
    through the shared cascade above it -- so admin never falls through to
    whatever the light/dark layers become."""
    declared = _admin_block_declarations()
    used = _vars_used_by_admin_css()
    missing = sorted(used - set(declared))
    assert not missing, (
        'admin.css uses tokens the [data-surface="admin"] block does not declare, so they '
        f"would fall through to the shared palette once it changes: {missing}"
    )


def test_admin_css_uses_exactly_the_tokens_this_file_pins():
    """Keeps LEGACY_ADMIN_TOKENS itself honest: if admin.css starts or stops
    using a token, this fails before the snapshot check below can silently
    keep passing against the wrong set."""
    used = _vars_used_by_admin_css()
    assert used == set(LEGACY_ADMIN_TOKENS), (
        f"admin.css's own var() usage no longer matches this file's pinned set -- "
        f"used but not pinned: {sorted(used - set(LEGACY_ADMIN_TOKENS))}, "
        f"pinned but unused: {sorted(set(LEGACY_ADMIN_TOKENS) - used)}"
    )


def test_admin_block_values_match_the_pinned_snapshot():
    """The admin block can only change deliberately: PR 3 deletes this whole
    section at once, so a value drifting one hex digit at a time here would
    otherwise go unnoticed until then."""
    declared = _admin_block_declarations()
    mismatched = {
        name: {"tokens.css": declared.get(name), "pinned": expected}
        for name, expected in LEGACY_ADMIN_TOKENS.items()
        if declared.get(name) != expected
    }
    assert not mismatched, f"admin block drifted from its pinned snapshot: {mismatched}"
