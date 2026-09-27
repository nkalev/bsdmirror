"""The keyboard focus ring (spec section 9, "Focus"): every interactive
element shows a 2px accent outline at a 2px offset.

One unconditional `:focus-visible` rule per stylesheet draws the ring for
every element at once, so this pins that rule rather than each control. Its
colour is --accent-primary, whose contrast against the surface and the ground
tests/test_contrast.py's token pairs pin in both themes.

Covers style.css. error.css joins STYLESHEETS once the error pages carry a
focus rule of their own (spec section 5.3).
"""
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STYLE_CSS = REPO_ROOT / "frontend" / "public" / "css" / "style.css"
STYLESHEETS = [STYLE_CSS]


def top_level_rules(css_text):
    """(selector, declarations) for every rule outside an at-rule, found by
    counting braces: a rule inside a @media block applies only some of the
    time, so it never counts as the page-wide ring."""
    css = re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)
    rules, depth, start, selector, body_start = [], 0, 0, "", 0
    for i, ch in enumerate(css):
        if ch == "{":
            if depth == 0:
                selector, body_start = css[start:i].strip(), i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                if not selector.startswith("@"):
                    rules.append((selector, css[body_start:i]))
                start = i + 1
    return rules


def declared(body, prop):
    m = re.search(rf"(?<![\w-]){re.escape(prop)}\s*:\s*([^;]+);", body)
    return " ".join(m.group(1).split()) if m else None


@pytest.mark.parametrize("sheet", STYLESHEETS, ids=[p.name for p in STYLESHEETS])
def test_focus_visible_draws_a_2px_accent_outline_at_a_2px_offset(sheet):
    rules = [
        body
        for selector, body in top_level_rules(sheet.read_text(encoding="utf-8"))
        if selector == ":focus-visible"
    ]
    assert (
        len(rules) == 1
    ), f"{sheet.name} has {len(rules)} top-level :focus-visible rules, expected 1"
    assert declared(rules[0], "outline") == "2px solid var(--accent-primary)"
    assert declared(rules[0], "outline-offset") == "2px"
