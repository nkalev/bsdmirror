"""WCAG 2.1 AA contrast for the public site and the admin panel.

Both surfaces run the "Reflection" palette (docs/design/2026-09-25-
reflection-redesign.md, sections 4.1-4.4, 4.7-4.9): the admin console follows
the same saved light/dark choice as the public site (section 6.2) and sets no
colour token of its own (section 7), so every ADMIN_PAIRS entry below is
checked against the exact same tokens the public site's LIGHT/DARK themes
already prove compliant, in both admin states. This file checks both
surfaces, but the two halves are largely independent day to day: a change to
the public palette should never need to touch ADMIN_PAIRS, and vice versa --
only a change to a token both surfaces share moves both at once, which is
exactly what the mutation tests below are for.

This file has two halves.

STATIC (always runs, no external tooling): reads style.css, admin.css and
tokens.css as text, resolves the same var() chains a browser's cascade would,
and does the WCAG relative-luminance arithmetic. Mirrors the house style in
test_error_pages_inline_styles.py (which parses tokens.css's dark block
directly rather than hand-copying its values) and test_admin_inline_styles.py
(whose stylesheet list is deliberately not a second, driftable copy of what a
page actually links). The pairs checked here are the ones a real element on
the page actually renders -- an element's own declared background where it has
one, its nearest styled ancestor's where it does not (documented per check) --
plus a token-level table for every pair spec section 9 names regardless of
whether a component rule happens to consume it today.

DYNAMIC (skips without node/Chrome): shells out to
tests/js/contrast_harness.mjs, which drives real headless Chrome and reads
getComputedStyle for the same elements, including two genuine :hover states
dispatched as real mouse input, every mirror-status pill and dot variant, and
the online stream line (the syncing and error lines are gradients, pinned at
token level), driven from a stubbed /api/ response and, where the stub cannot
naturally reach a variant (the neutral pill, three of the four status-dot
states), by setting data-state on the element directly -- CSS keys off the
attribute alone, so that is a faithful probe of the same rule the static half
parses. What the static half cannot see on its own: whether the browser's
actual cascade -- specificity, inheritance, a CSS transition sampled
mid-fade -- agrees with what a text-only parser assumed. See that file's
docstring for the rest of the trade-offs (most notably: it reaches admin.js's
markup by calling its page-renderer functions directly, the same way
tests/js/escaping_harness.mjs does, rather than driving the SPA through a
live backend).

Both halves are mutation-tested: tests/test_admin_js_escaping.py's reasoning
applies here word for word -- a guard only ever seen passing is
indistinguishable from one that cannot fail.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKENS_CSS = REPO_ROOT / "frontend" / "public" / "css" / "tokens.css"
STYLE_CSS = REPO_ROOT / "frontend" / "public" / "css" / "style.css"
ADMIN_CSS = REPO_ROOT / "frontend" / "public" / "admin" / "css" / "admin.css"
ADMIN_JS = REPO_ROOT / "frontend" / "public" / "admin" / "js" / "admin.js"
HARNESS = REPO_ROOT / "tests" / "js" / "contrast_harness.mjs"


# ===========================================================================
# WCAG 2.1 relative luminance / contrast ratio
#
# https://www.w3.org/TR/WCAG21/#dfn-relative-luminance and #dfn-contrast-ratio.
# The one implementation dynamic measurements are also checked against
# (test_contrast_ratio_matches_the_wcag_worked_examples pins it to the
# spec's own numbers).
# ===========================================================================
def _hex_to_rgb(value):
    value = value.lstrip("#")
    assert len(value) == 6, f"expected a 6-digit hex colour, got {value!r}"
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _srgb_channel_to_linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color):
    r, g, b = _hex_to_rgb(hex_color)
    R, G, B = (_srgb_channel_to_linear(c) for c in (r, g, b))
    return 0.2126 * R + 0.7152 * G + 0.0722 * B


def contrast_ratio(hex_a, hex_b):
    la, lb = relative_luminance(hex_a), relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def composite(fg_hex, alpha, bg_hex):
    """Alpha-blend fg over bg, both given as opaque hex, in sRGB-encoded
    space -- how a browser paints a translucent rgba() box over a solid one."""
    fr, fg_, fb = _hex_to_rgb(fg_hex)
    br, bg_, bb = _hex_to_rgb(bg_hex)
    return "#%02X%02X%02X" % (
        round(fr * alpha + br * (1 - alpha)),
        round(fg_ * alpha + bg_ * (1 - alpha)),
        round(fb * alpha + bb * (1 - alpha)),
    )


def test_contrast_ratio_matches_the_wcag_worked_examples():
    """Pins the formula itself, independent of this app's tokens, against
    values anyone can check by hand: pure black on white is exactly 21:1,
    and swapping the two arguments must not change the answer."""
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("#FFFFFF", "#000000") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("#777777", "#777777") == pytest.approx(1.0, abs=0.001)


def test_composite_matches_simple_alpha_blend_arithmetic():
    assert composite("#FF0000", 0.0, "#00FF00") == "#00FF00"
    assert composite("#FF0000", 1.0, "#00FF00") == "#FF0000"
    assert composite("#FFFFFF", 0.5, "#000000") == "#808080"


# ===========================================================================
# A tiny CSS reader: comment stripping, at-rule stripping, exact-selector
# block lookup, declaration lookup, and var() resolution against tokens.css's
# cascade.
#
# Deliberately not a general CSS parser -- just enough to answer "what does
# this exact selector declare for this exact property", the same scope
# test_error_pages_inline_styles.py's regexes keep to.
# ===========================================================================
_RULE_RE = re.compile(r"([^{}]+)\{([^}]*)\}")
_AT_RULE_OPEN = re.compile(r"@(?:media|keyframes)\b[^{]*\{")


def strip_css_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def strip_at_rule_bodies(css):
    """Removes every top-level @media/@keyframes block, brace-depth-counted
    by hand rather than left to _RULE_RE (which has no concept of nesting):
    _RULE_RE's `[^}]*` body stops at the FIRST `}` it meets, so the first
    rule nested inside one of these blocks merges into the at-rule's own
    "selector" (swallowing that rule's opening brace), and every rule AFTER
    the first then looks exactly like an ordinary, unconditional top-level
    rule to _RULE_RE -- selector text and all. A selector reused inside a
    responsive override or a @keyframes step then makes find_block() see its
    real, unconditional rule "twice" (style.css has this shape today: a
    top-level `.access-grid` under Mirrors/Access, and another one -- a
    responsive override, one column instead of auto-fit -- inside `@media
    (max-width: 639.98px)`). Removing the whole block first means _RULE_RE
    only ever sees the rules a pinned selector is actually meant to name: an
    unconditional, always-applied one. See
    test_find_block_is_not_fooled_by_a_selector_reused_inside_at_rules for
    the regression this fixes.
    """
    out, pos = [], 0
    for m in _AT_RULE_OPEN.finditer(css):
        if m.start() < pos:
            continue  # already inside a block this loop is removing
        out.append(css[pos : m.start()])
        depth, i = 1, m.end()
        while depth > 0 and i < len(css):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        pos = i
    out.append(css[pos:])
    return "".join(out)


def _prepared_css(css_text):
    """Comments, then @media/@keyframes bodies, stripped in that order: a
    comment could itself contain a brace, which would desync
    strip_at_rule_bodies()'s hand-rolled depth counter if it ran first."""
    return strip_at_rule_bodies(strip_css_comments(css_text))


def test_strip_at_rule_bodies_removes_nested_media_and_keyframes():
    css = (
        ".access-grid { grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }\n"
        "@media (max-width: 639.98px) {\n"
        "    .access-grid { grid-template-columns: 1fr; }\n"
        "    .nav { display: none; }\n"
        "}\n"
        "@keyframes spin {\n"
        "    0% { transform: rotate(0deg); }\n"
        "    100% { transform: rotate(360deg); }\n"
        "}\n"
    )
    prepared = strip_at_rule_bodies(css)
    assert "@media" not in prepared
    assert "@keyframes" not in prepared
    assert "639.98px" not in prepared
    assert "rotate" not in prepared
    # The real, unconditional rule survives untouched.
    assert (
        ".access-grid { grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }" in prepared
    )


def test_find_block_is_not_fooled_by_a_selector_reused_inside_at_rules():
    """Pins the _RULE_RE nested-at-rule bug directly, with a minimal repro
    of style.css's real shape: a responsive override of ".access-grid" that
    is not the first rule in its @media block. The first nested rule is the
    one _RULE_RE merges into the at-rule's own "selector", so the repro needs
    a rule ahead of the override, as style.css has (".nav" there). Without
    strip_at_rule_bodies(), find_block() sees ".access-grid" twice (its real
    top-level rule, plus the override, which _RULE_RE's brace-per-rule
    matching cannot tell apart from a second top-level one) and raises
    "found 2 times, expected 1" -- a false failure on a perfectly ordinary
    responsive override, for a selector nobody had touched."""
    css = (
        ".access-grid { grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }\n"
        "@media (max-width: 639.98px) {\n"
        "    .nav { display: none; }\n"
        "    .access-grid { grid-template-columns: 1fr; }\n"
        "}\n"
    )
    block = find_block(css, ".access-grid")
    assert block.strip() == "grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));"


def find_block(css_text, selector):
    """The declaration body of the one rule whose selector, once stripped of
    surrounding whitespace, is exactly `selector` -- not a substring match,
    so `.nav-link` cannot accidentally match `.nav-link:hover` and a combined
    selector like `th,\\ntd` cannot accidentally match `th`. Only ever looks
    at top-level rules: see strip_at_rule_bodies() above for why a selector
    inside a @media/@keyframes block must not count."""
    css = _prepared_css(css_text)
    matches = [body for sel, body in _RULE_RE.findall(css) if sel.strip() == selector]
    assert matches, f"no exact {selector!r} rule found"
    assert len(matches) == 1, f"{selector!r} rule found {len(matches)} times, expected 1"
    return matches[0]


_PROP_TEMPLATE = r"(?<![\w-]){prop}(?![\w-])\s*:\s*([^;]+);"


def declared(block, prop):
    """The value of an exact property name in a declaration block. The
    negative look-around stops `background` from matching inside
    `background-color`."""
    m = re.search(_PROP_TEMPLATE.format(prop=re.escape(prop)), block)
    assert m, f"no {prop!r} declaration in block {block!r}"
    return m.group(1).strip()


def declared_background(block):
    """`background-color` if present, else the shorthand `background` --
    every component rule this file reads uses one or the other for a single
    solid colour, never both."""
    for prop in ("background-color", "background"):
        m = re.search(_PROP_TEMPLATE.format(prop=prop), block)
        if m:
            return m.group(1).strip()
    raise AssertionError(f"no background/background-color in block {block!r}")


def var_ref(value):
    m = re.fullmatch(r"var\((--[\w-]+)\)", value)
    assert m, f"expected a bare var(--x) reference, got {value!r}"
    return m.group(1)


# A handful of CSS keyword colours, needed only so the mutation tests below
# can plant a literal like `color: white` and have the checker compute a
# real (failing) ratio for it, instead of tripping var_ref()'s assertion on a
# value that was never a token reference to begin with. No real, un-mutated
# rule in style.css/admin.css uses one of these any more.
_NAMED_COLORS = {"white": "#FFFFFF", "black": "#000000"}


def color_hex(theme, raw_value):
    """Resolve a declared colour value -- var(--x), a bare hex, or a CSS
    keyword -- to a plain #RRGGBB against `theme`."""
    raw_value = raw_value.strip()
    m = re.fullmatch(r"var\((--[\w-]+)\)", raw_value)
    if m:
        return resolved_hex(theme, m.group(1))
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", raw_value):
        return raw_value.upper()
    if raw_value.lower() in _NAMED_COLORS:
        return _NAMED_COLORS[raw_value.lower()]
    raise AssertionError(f"unrecognised colour value: {raw_value!r}")


# ===========================================================================
# tokens.css: build one resolved dict of custom properties per theme
# ===========================================================================
def parse_custom_properties(block):
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block))


def build_themes(tokens_css_text):
    """Returns (light, dark, admin_light, admin_dark), each {token_name: raw
    value string}.

    Raw, not yet resolved through var() -- resolve()/resolved_hex() below walk
    the chain at lookup time using whichever of these dicts is asked, so a
    token that is only overridden for one theme still resolves correctly
    through the layers under it.

    admin_light and admin_dark mirror the two real states a browser actually
    renders (spec section 6.2): [data-surface="admin"] alone -- data-theme
    absent, i.e. light -- and [data-theme="dark"][data-surface="admin"]
    together. Since [data-theme="dark"] does not match at all in the first
    state, admin_light is light-plus-admin, never dark-plus-admin, unlike the
    single always-dark `admin` this function returned before the admin
    console followed the theme toggle (spec section 6.1's "Admin is dark-only"
    is gone, along with the LEGACY ADMIN block).
    """
    css = _prepared_css(tokens_css_text)
    root_bodies, dark_body, admin_body = [], None, None
    for sel, body in _RULE_RE.findall(css):
        sel = sel.strip()
        if sel == ":root":
            root_bodies.append(body)
        elif sel == '[data-theme="dark"]':
            assert dark_body is None, 'more than one [data-theme="dark"] block'
            dark_body = body
        elif sel == '[data-surface="admin"]':
            assert admin_body is None, 'more than one [data-surface="admin"] block'
            admin_body = body

    assert (
        len(root_bodies) == 3
    ), f"expected 3 :root blocks (primitives, invariants, light theme), found {len(root_bodies)}"
    assert dark_body is not None, 'no [data-theme="dark"] block found'
    assert admin_body is not None, 'no [data-surface="admin"] block found'

    light = {}
    for body in root_bodies:
        light.update(parse_custom_properties(body))

    dark = dict(light)
    dark.update(parse_custom_properties(dark_body))

    admin_light = dict(light)
    admin_light.update(parse_custom_properties(admin_body))

    admin_dark = dict(dark)
    admin_dark.update(parse_custom_properties(admin_body))

    return light, dark, admin_light, admin_dark


def resolve(theme, name, _seen=frozenset()):
    assert name not in _seen, f"cycle resolving {name}: {_seen}"
    assert name in theme, f"{name} is not defined in this theme"
    value = theme[name].strip()
    m = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if m:
        return resolve(theme, m.group(1), _seen | {name})
    return value


def resolved_hex(theme, name):
    value = resolve(theme, name)
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), (
        f"{name} does not resolve to a plain hex colour (got {value!r}); "
        f"a gradient or non-colour token was asked for a solid colour"
    )
    return value.upper()


TOKENS_TEXT = TOKENS_CSS.read_text(encoding="utf-8")
LIGHT, DARK, ADMIN_LIGHT, ADMIN_DARK = build_themes(TOKENS_TEXT)


def test_the_admin_layer_sets_no_colour_token():
    """Spec section 7: the admin console's own redesign folds every one of
    its colours back into the shared light/dark layers, leaving
    [data-surface="admin"] with nothing but its one non-colour override
    (--sidebar-width). A colour token reintroduced there would silently
    re-freeze whatever pair it backs at today's value, exactly the LEGACY
    ADMIN bug this same block used to be on purpose
    (tests/test_legacy_admin_tokens.py, deleted alongside it) -- so this
    checks the block's own declarations directly, not merely that
    ADMIN_LIGHT/ADMIN_DARK happen to resolve like LIGHT/DARK today.

    The block is pinned to exactly that one declaration rather than scanned
    for colour-looking names. A list of name prefixes passes any colour token
    named outside it (--surface-raised, --danger) and any declaration that is
    not a custom property at all (a `color:` or a `background:` written
    straight into the block). A second declaration here is a decision to make
    in this test, with section 7 of the spec beside it."""
    block = find_block(TOKENS_TEXT, '[data-surface="admin"]')
    declared_names = [
        declaration.split(":", 1)[0].strip()
        for declaration in block.split(";")
        if declaration.strip()
    ]
    assert declared_names == ["--sidebar-width"], (
        '[data-surface="admin"] must declare exactly --sidebar-width and nothing else '
        f"(spec section 7); it declares {declared_names}"
    )


# ===========================================================================
# .header's own background is a literal translucent rgba(), not a
# var(--bg-*) token -- it needs the alpha for the sticky/blurred header
# effect. .nav-link, .nav-admin and .wordmark have no background of their
# own, so the backdrop they actually render against is that rgba() composited
# over whatever is behind the header: --bg-primary, the page background.
#
# Keyed on the theme LABEL, not on `theme is DARK`: the real (non-mutated)
# checks below always pass this module's own LIGHT/DARK singletons, so
# `is DARK` happened to work for them, but every mutation test rebuilds a
# fresh pair of dicts via build_themes() -- equal by value, never `is DARK`
# -- and a fresh "dark" dict was silently scored against the LIGHT .header
# rule instead. See test_header_ambient_background_uses_the_dark_selector_
# for_a_copied_dict for the regression this fixes.
# ===========================================================================
def header_ambient_background(style_css_text, theme, theme_label):
    selector = '[data-theme="dark"] .header' if theme_label == "dark" else ".header"
    block = find_block(style_css_text, selector)
    value = declared_background(block)
    m = re.fullmatch(
        r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)", value
    )
    assert m, f"{selector} background is not a plain rgb()/rgba(): {value!r}"
    r, g, b = (float(m.group(i)) for i in (1, 2, 3))
    alpha = float(m.group(4)) if m.group(4) is not None else 1.0
    literal_hex = "#%02X%02X%02X" % (round(r), round(g), round(b))
    return composite(literal_hex, alpha, resolved_hex(theme, "--bg-primary"))


def test_header_ambient_background_uses_the_dark_selector_for_a_copied_dict():
    """header_ambient_background used to decide light vs dark with
    `theme is DARK`, true only for this module's own singleton. A dict that
    is merely equal to DARK -- exactly what every mutation test hands it,
    via a fresh build_themes() call -- used to fall through to the LIGHT
    `.header` rule instead, silently scoring a dark-theme header pairing
    against the wrong backdrop. text_secondary_dark_reverts_to_the_other_
    themes_shade below is the mutation that actually found this: under the
    old identity check it measured 4.62:1 against the light header (a false
    pass) where the real, dark header gives 2.67:1 (a real failure)."""
    copied_dark = dict(DARK)
    assert copied_dark is not DARK
    assert header_ambient_background(
        STYLE_CSS_TEXT, copied_dark, "dark"
    ) == header_ambient_background(STYLE_CSS_TEXT, DARK, "dark")


# ===========================================================================
# The pairs the public site actually renders (style.css)
#
# Each entry: (id, fg_selector, fg_prop, bg_source, min_ratio). bg_source is
# ("own", ) for the same block's own background, ("parent", selector) for a
# named ancestor rule's background (however many DOM levels up -- neither
# side of this file tracks real nesting depth, only which rule to read),
# ("body", ) for the page's own background where the element's whole ancestor
# chain declares none of its own, or ("header", ) for the header's special
# translucent composite. Checked in both light and dark, since main.js can
# set either on the public site.
# ===========================================================================
PUBLIC_PAIRS = [
    ("body", "body", "color", ("own",), 4.5),
    (".nav-link", ".nav-link", "color", ("header",), 4.5),
    (".nav-link:hover", ".nav-link:hover", "color", ("own",), 4.5),
    (".nav-admin", ".nav-admin", "color", ("header",), 4.5),
    (".wordmark", ".wordmark", "color", ("header",), 4.5),
    # .hero/.hero-copy/.stat declare no background of their own; what
    # actually renders behind .stat-label is body's own --bg-primary.
    (".stat-label", ".stat-label", "color", ("body",), 4.5),
    (".mirror-description", ".mirror-description", "color", ("parent", ".mirror-card"), 4.5),
    # .mirror-details itself has no background; two levels up to the card.
    (".mirror-details dt", ".mirror-details dt", "color", ("parent", ".mirror-card"), 4.5),
    (".btn-primary", ".btn-primary", "color", ("own",), 4.5),
    (".btn-secondary:hover", ".btn-secondary:hover", "color", ("own",), 4.5),
    (".access-label", ".access-label", "color", ("parent", ".access-row"), 4.5),
    (".footer-content p", ".footer-content p", "color", ("parent", ".footer"), 4.5),
    (".footer-content a", ".footer-content a", "color", ("parent", ".footer"), 4.5),
    (".about-text a", ".about-text a", "color", ("body",), 4.5),
    (".section-subtitle", ".section-subtitle", "color", ("body",), 4.5),
    (".toast", ".toast", "color", ("own",), 4.5),
    # Pills (spec section 4.8): keyed only by data-state, never a class
    # rewrite. Neutral (the base rule, used for "disabled"/"unknown") plus
    # the three named states.
    (".pill", ".pill", "color", ("own",), 4.5),
    ('.pill[data-state="online"]', '.pill[data-state="online"]', "color", ("own",), 4.5),
    ('.pill[data-state="syncing"]', '.pill[data-state="syncing"]', "color", ("own",), 4.5),
    ('.pill[data-state="error"]', '.pill[data-state="error"]', "color", ("own",), 4.5),
    # The overall status card's dot: a UI indicator (WCAG 2.1 SC 1.4.11,
    # 3:1), not text -- fg_prop is `background` (the dot's own fill), and
    # the surface it sits on is .status-card's own --bg-card, regardless of
    # which data-state rule (if any) currently overrides the dot's colour.
    (".status-dot", ".status-dot", "background", ("parent", ".status-card"), 3.0),
    (
        '.status-card[data-state="online"] .status-dot',
        '.status-card[data-state="online"] .status-dot',
        "background",
        ("parent", ".status-card"),
        3.0,
    ),
    (
        '.status-card[data-state="syncing"] .status-dot',
        '.status-card[data-state="syncing"] .status-dot',
        "background",
        ("parent", ".status-card"),
        3.0,
    ),
    (
        '.status-card[data-state="error"] .status-dot',
        '.status-card[data-state="error"] .status-dot',
        "background",
        ("parent", ".status-card"),
        3.0,
    ),
    # The one sync-stream state with a bare var() background; syncing/error
    # paint with a gradient (see the note below PUBLIC_CHECKS).
    (
        '.stream[data-state="online"] .stream-line::before',
        '.stream[data-state="online"] .stream-line::before',
        "background",
        ("parent", ".streams-inner"),
        3.0,
    ),
]


def compute_public_checks(style_css_text, themes):
    """themes: {label: theme_dict}. Returns [(check_id, ratio, min_ratio, fg_hex, bg_hex)]."""
    results = []
    for label, theme in themes.items():
        for check_id, fg_selector, fg_prop, bg_source, min_ratio in PUBLIC_PAIRS:
            fg_block = find_block(style_css_text, fg_selector)
            fg_hex = color_hex(theme, declared(fg_block, fg_prop))

            kind = bg_source[0]
            if kind == "own":
                bg_hex = color_hex(theme, declared_background(fg_block))
            elif kind == "parent":
                bg_block = find_block(style_css_text, bg_source[1])
                bg_hex = color_hex(theme, declared_background(bg_block))
            elif kind == "body":
                body_block = find_block(style_css_text, "body")
                bg_hex = color_hex(theme, declared_background(body_block))
            elif kind == "header":
                bg_hex = header_ambient_background(style_css_text, theme, label)
            else:  # pragma: no cover - guards a typo in PUBLIC_PAIRS itself
                raise AssertionError(f"unknown bg_source kind {kind!r}")

            ratio = contrast_ratio(fg_hex, bg_hex)
            results.append((f"{check_id} [{label}]", ratio, min_ratio, fg_hex, bg_hex))
    return results


# Not selector-pinnable, and not worth making so: the syncing stream's dots
# and the error stream's dashed line are radial-gradient()/repeating-linear-
# gradient() values wrapping the token, not a bare var(), so color_hex()
# would reject them by design -- that guard is doing its job. Both are
# covered instead by the token-level table below, which needs no CSS
# parsing at all.
STYLE_CSS_TEXT = STYLE_CSS.read_text(encoding="utf-8")
PUBLIC_CHECKS = compute_public_checks(STYLE_CSS_TEXT, {"light": LIGHT, "dark": DARK})


@pytest.mark.parametrize(
    "check_id,ratio,min_ratio,fg_hex,bg_hex",
    PUBLIC_CHECKS,
    ids=[c[0] for c in PUBLIC_CHECKS],
)
def test_public_site_contrast(check_id, ratio, min_ratio, fg_hex, bg_hex):
    assert (
        ratio >= min_ratio
    ), f"{check_id}: {fg_hex} on {bg_hex} is {ratio:.2f}:1, needs >= {min_ratio}:1"


def test_footer_version_declares_no_opacity():
    """opacity multiplies straight through whatever colour is behind it and
    is invisible to a colour-token contrast check (getComputedStyle().color
    is unaffected by opacity; it is a paint-time effect) -- an opacity here
    could take an already-compliant --text-secondary back down below 4.5:1
    without any of the ratio checks above ever seeing it, since
    .footer-version declares no colour of its own (it inherits
    .footer-content p's, covered above)."""
    block = find_block(STYLE_CSS_TEXT, ".footer-version")
    m = re.search(_PROP_TEMPLATE.format(prop="opacity"), block)
    assert m is None or m.group(1).strip() in ("1", "1.0"), (
        f".footer-version declares opacity: {m.group(1) if m else None!r}, which "
        f"fades --text-secondary below 4.5:1 against --bg-secondary in both themes"
    )


# ===========================================================================
# The token-level pairs spec section 9 names, resolved directly from
# tokens.css in both themes -- independent of whether a component rule in
# style.css happens to consume a given pair today. Two of these
# (--status-info, --status-incomplete) have no consumer on the public site --
# they back the admin console's info/incomplete pills instead (spec section
# 4.8's table; see ADMIN_PAIRS' .status-badge.info/.pending/.health-incomplete
# rows); --border-strong reaches the public site only as two hover borders (a
# border-color, which no selector pair above reads) and backs three admin
# control edges the same way (spec section 9; not separately selector-pinned
# in ADMIN_PAIRS, see the note above compute_admin_checks()); the disk meter's
# fills are consumed only by the admin console (spec section 4.8, "Disk
# meter") -- all of them are pinned here, so each is checked wherever it is
# actually consumed, in both public themes and, since the admin surface sets
# no colour of its own, in both admin states for free.
# ===========================================================================
TOKEN_PAIRS = [
    ("--text-primary", "--bg-primary", 4.5),
    ("--text-primary", "--bg-card", 4.5),
    ("--text-primary", "--bg-secondary", 4.5),
    ("--text-secondary", "--bg-primary", 4.5),
    ("--text-secondary", "--bg-card", 4.5),
    ("--text-secondary", "--bg-secondary", 4.5),
    ("--accent-primary", "--bg-primary", 4.5),
    ("--accent-primary", "--bg-card", 4.5),
    ("--text-on-accent", "--accent-primary", 4.5),
    ("--status-healthy", "--status-healthy-bg", 4.5),
    ("--status-syncing", "--status-syncing-bg", 4.5),
    ("--status-error", "--status-error-bg", 4.5),
    ("--status-info", "--status-info-bg", 4.5),
    ("--status-incomplete", "--status-incomplete-bg", 4.5),
    ("--border-strong", "--bg-card", 3.0),
    ("--stream-line", "--bg-card", 3.0),
    ("--status-healthy", "--bg-card", 3.0),
    ("--status-syncing", "--bg-card", 3.0),
    ("--status-error", "--bg-card", 3.0),
    # admin.css's .log-pre-error (spec 6.1: "log blocks ... in mono") reads
    # --status-error directly against --bg-secondary; no other component pair
    # covers that background, so it gets a row of its own.
    ("--status-error", "--bg-secondary", 4.5),
    # The disk meter: each fill against the track (--border-color), 3:1. The
    # tick at 85% (--text-primary on --bg-card, 3:1) has no row of its own:
    # the 4.5:1 text pair at the top of this list is the same two tokens at
    # a stricter threshold, and a second row would repeat its check id.
    ("--text-secondary", "--border-color", 3.0),
    ("--status-syncing", "--border-color", 3.0),
    ("--status-error", "--border-color", 3.0),
]


def compute_token_checks(themes):
    """themes: {label: theme_dict}. Same return shape as compute_public_checks."""
    results = []
    for label, theme in themes.items():
        for fg, bg, min_ratio in TOKEN_PAIRS:
            fg_hex, bg_hex = resolved_hex(theme, fg), resolved_hex(theme, bg)
            ratio = contrast_ratio(fg_hex, bg_hex)
            results.append((f"{fg} on {bg} [{label}]", ratio, min_ratio, fg_hex, bg_hex))
    return results


TOKEN_CHECKS = compute_token_checks({"light": LIGHT, "dark": DARK})


@pytest.mark.parametrize(
    "check_id,ratio,min_ratio,fg_hex,bg_hex", TOKEN_CHECKS, ids=[c[0] for c in TOKEN_CHECKS]
)
def test_token_level_contrast(check_id, ratio, min_ratio, fg_hex, bg_hex):
    assert (
        ratio >= min_ratio
    ), f"{check_id}: {fg_hex} on {bg_hex} is {ratio:.2f}:1, needs >= {min_ratio}:1"


# ===========================================================================
# The pairs the admin panel actually renders (admin.css). The admin console
# now follows the same saved light/dark choice as the public site (spec
# section 6.2), so every pair here is checked in both ADMIN_LIGHT and
# ADMIN_DARK -- see compute_admin_checks(). Since the admin layer sets no
# colour token of its own any more (spec section 7), every one of these
# resolves through the exact same tokens the public site's LIGHT/DARK themes
# already do; nothing here is a colour admin alone invented.
# ===========================================================================
# fmt: off
ADMIN_PAIRS = [
    # --- Shell: sidebar, header, the theme toggle -------------------------
    ("body", "body", "color", ("own",), 4.5),
    (".loading-screen", ".loading-screen", "color", ("parent", "body"), 4.5),
    (".wordmark", ".wordmark", "color", ("parent", ".sidebar"), 4.5),
    (".nav-section-title", ".nav-section-title", "color", ("parent", ".sidebar"), 4.5),
    (".nav-item", ".nav-item", "color", ("parent", ".sidebar"), 4.5),
    (".nav-item:hover", ".nav-item:hover", "color", ("own",), 4.5),
    (".nav-item.active", ".nav-item.active", "color", ("own",), 4.5),
    (".user-name", ".user-name", "color", ("parent", ".user-info"), 4.5),
    (".user-role", ".user-role", "color", ("parent", ".user-info"), 4.5),
    (".user-avatar", ".user-avatar", "color", ("own",), 4.5),
    (".header-title", ".header-title", "color", ("parent", ".header"), 4.5),
    (".theme-toggle", ".theme-toggle", "color", ("own",), 4.5),
    # --- Cards and KPI tiles (spec 6.1) ------------------------------------
    (".card-title", ".card-title", "color", ("parent", ".card"), 4.5),
    (".card-subtitle", ".card-subtitle", "color", ("parent", ".card"), 4.5),
    (".stat-card-icon", ".stat-card-icon", "color", ("own",), 4.5),
    (".stat-card-trend.up", ".stat-card-trend.up", "color", ("own",), 4.5),
    (".stat-card-trend.down", ".stat-card-trend.down", "color", ("own",), 4.5),
    (".stat-card-value", ".stat-card-value", "color", ("parent", ".stat-card"), 4.5),
    (".stat-card-label", ".stat-card-label", "color", ("parent", ".stat-card"), 4.5),
    # --- Tables -------------------------------------------------------------
    ("th", "th", "color", ("own",), 4.5),
    ("td", "td", "color", ("parent", ".card"), 4.5),
    # td's own rule sets no colour of its own on hover, so the text is still
    # td's --text-primary; only the background changes. fg_selector reads the
    # unconditional rule, bg_source reads the hover rule's own fill.
    ("tr:hover td", "td", "color", ("parent", "tr:hover td"), 4.5),
    # --- Status pills (spec 4.8): the bare/neutral rule, then every named
    # modifier the job, mirror, protection and role pills can render. Each is
    # its own standalone rule (never grouped), even where two modifiers share
    # a colour -- see admin.css's status-badge section. --------------------
    (".status-badge", ".status-badge", "color", ("own",), 4.5),
    (".status-badge.disabled", ".status-badge.disabled", "color", ("own",), 4.5),
    (".status-badge.cancelled", ".status-badge.cancelled", "color", ("own",), 4.5),
    (".status-badge.active", ".status-badge.active", "color", ("own",), 4.5),
    (".status-badge.completed", ".status-badge.completed", "color", ("own",), 4.5),
    (".status-badge.syncing", ".status-badge.syncing", "color", ("own",), 4.5),
    (".status-badge.running", ".status-badge.running", "color", ("own",), 4.5),
    (".status-badge.at-risk", ".status-badge.at-risk", "color", ("own",), 4.5),
    (".status-badge.error", ".status-badge.error", "color", ("own",), 4.5),
    (".status-badge.failed", ".status-badge.failed", "color", ("own",), 4.5),
    (".status-badge.info", ".status-badge.info", "color", ("own",), 4.5),
    (".status-badge.pending", ".status-badge.pending", "color", ("own",), 4.5),
    # "incomplete": the health-checks card only (spec 4.8: kept distinct from
    # neutral, so it is never mistaken for "Unknown").
    (".status-badge.health-incomplete", ".status-badge.health-incomplete", "color", ("own",), 4.5),
    # --- Recent Sync Jobs / Recent Activity, and the health-checks card ----
    (".activity-icon", ".activity-icon", "color", ("own",), 4.5),
    (".activity-text", ".activity-text", "color", ("parent", ".card"), 4.5),
    (".activity-time", ".activity-time", "color", ("parent", ".card"), 4.5),
    (".health-check-icon", ".health-check-icon", "color", ("parent", ".card"), 4.5),
    (".health-check-icon.is-bad", ".health-check-icon.is-bad", "color", ("parent", ".card"), 4.5),
    (".health-check-icon.is-warn", ".health-check-icon.is-warn", "color", ("parent", ".card"), 4.5),
    (".health-check-icon.is-ok", ".health-check-icon.is-ok", "color", ("parent", ".card"), 4.5),
    (".health-check-icon.is-skip", ".health-check-icon.is-skip", "color", ("parent", ".card"), 4.5),
    (".health-check-text", ".health-check-text", "color", ("parent", ".card"), 4.5),
    # --- Forms (spec 6.1: "fields never sit directly on the page ground") -
    # .form-label sits inside either a plain .card (Settings) or a .modal
    # (add/edit user); both share --bg-card, so either name reads the same
    # fill.
    (".form-label", ".form-label", "color", ("parent", ".card"), 4.5),
    (".form-input", ".form-input", "color", ("own",), 4.5),
    (".form-input::placeholder", ".form-input::placeholder", "color", ("parent", ".form-input"), 4.5),
    # --- Buttons ------------------------------------------------------------
    (".btn-primary", ".btn-primary", "color", ("own",), 4.5),
    (".btn-secondary", ".btn-secondary", "color", ("own",), 4.5),
    (".btn-danger", ".btn-danger", "color", ("own",), 4.5),
    # --- Modal ----------------------------------------------------------------
    (".modal-title", ".modal-title", "color", ("parent", ".modal"), 4.5),
    (".modal-close", ".modal-close", "color", ("parent", ".modal"), 4.5),
    # --- Login page -----------------------------------------------------------
    (".login-title", ".login-title", "color", ("parent", ".login-card"), 4.5),
    (".login-subtitle", ".login-subtitle", "color", ("parent", ".login-card"), 4.5),
    # --- Toasts: the message text, then the type icon (spec 4.7) ----------
    (".toast", ".toast", "color", ("own",), 4.5),
    (".toast.success .icon", ".toast.success .icon", "color", ("parent", ".toast"), 4.5),
    (".toast.error .icon", ".toast.error .icon", "color", ("parent", ".toast"), 4.5),
    (".toast.info .icon", ".toast.info .icon", "color", ("parent", ".toast"), 4.5),
    # --- Code and logs (spec 6.1: "code chips and log blocks on
    # --bg-secondary, in mono") ---------------------------------------------
    (".code-block", ".code-block", "color", ("own",), 4.5),
    # The location-name chips joinCodeList's <code> elements render as, once
    # scoped by the .code-chip-list wrapper (renderMirrorInventoryCard,
    # releaseRows). Its own solid background, not the ambient card/table one.
    (".code-chip-list code", ".code-chip-list code", "color", ("own",), 4.5),
    (".log-pre", ".log-pre", "color", ("own",), 4.5),
    (".log-pre-error", ".log-pre-error", "color", ("parent", ".log-pre"), 4.5),
    # --- Utilities ------------------------------------------------------------
    (".u-text-muted", ".u-text-muted", "color", ("parent", ".card"), 4.5),
    (".u-text-error", ".u-text-error", "color", ("parent", ".card"), 4.5),
    # --- Disk meter (spec 4.8): UI indicators, not text, so 3:1 against the
    # track (.meter) or the tile (.stat-card), read from `background` rather
    # than `color` -- the same shape the public site's .status-dot and
    # .stream-line::before pairs use. The tick at 85% is proved at the
    # stricter 4.5:1 already, by the shared --text-primary on --bg-card pair
    # above (.stat-card-value), so it gets no --text-primary-on-border-color
    # entry of its own -- only its own selector, at the 3:1 floor that
    # actually applies to it. ------------------------------------------------
    (".meter-fill", ".meter-fill", "background", ("parent", ".meter"), 3.0),
    (".meter-fill.is-warn", ".meter-fill.is-warn", "background", ("parent", ".meter"), 3.0),
    (".meter-fill.is-crit", ".meter-fill.is-crit", "background", ("parent", ".meter"), 3.0),
    (".meter-tick", ".meter-tick", "background", ("parent", ".stat-card"), 3.0),
]
# fmt: on

# The three --border-strong edges spec 9 also calls out (.btn-secondary,
# .form-input, .theme-toggle, all at least 3:1 against --bg-card) are
# deliberately not selector-pinned here: .form-input and .theme-toggle
# declare theirs through the `border: 1px solid var(--border-strong)`
# shorthand, which is not a bare var() in the one property color_hex()
# recognises (declared() would return the whole shorthand value, not just the
# colour). All three already resolve through the shared --border-strong on
# --bg-card pair TOKEN_PAIRS proves in both LIGHT and DARK below, and since
# the admin layer sets no --border-* token of its own, that same proof holds
# for ADMIN_LIGHT/ADMIN_DARK for free -- see compute_admin_checks()'s
# docstring.


def compute_admin_checks(admin_css_text, themes):
    """themes: {label: theme_dict} -- ADMIN_LIGHT and ADMIN_DARK, the two
    states a browser actually renders (data-surface="admin" alone, and
    together with data-theme="dark"). Same shape as compute_public_checks()/
    compute_token_checks(), so a mutation that reruns one reruns all three the
    same way."""
    results = []
    for label, theme in themes.items():
        for check_id, fg_selector, fg_prop, bg_source, min_ratio in ADMIN_PAIRS:
            fg_block = find_block(admin_css_text, fg_selector)
            fg_hex = color_hex(theme, declared(fg_block, fg_prop))

            kind = bg_source[0]
            if kind == "own":
                bg_hex = color_hex(theme, declared_background(fg_block))
            elif kind == "parent":
                bg_block = find_block(admin_css_text, bg_source[1])
                bg_hex = color_hex(theme, declared_background(bg_block))
            else:  # pragma: no cover
                raise AssertionError(f"unknown bg_source kind {kind!r}")

            ratio = contrast_ratio(fg_hex, bg_hex)
            results.append((f"{check_id} [{label}]", ratio, min_ratio, fg_hex, bg_hex))
    return results


ADMIN_CSS_TEXT = ADMIN_CSS.read_text(encoding="utf-8")
ADMIN_CHECKS = compute_admin_checks(ADMIN_CSS_TEXT, {"light": ADMIN_LIGHT, "dark": ADMIN_DARK})


@pytest.mark.parametrize(
    "check_id,ratio,min_ratio,fg_hex,bg_hex", ADMIN_CHECKS, ids=[c[0] for c in ADMIN_CHECKS]
)
def test_admin_panel_contrast(check_id, ratio, min_ratio, fg_hex, bg_hex):
    assert (
        ratio >= min_ratio
    ), f"{check_id}: {fg_hex} on {bg_hex} is {ratio:.2f}:1, needs >= {min_ratio}:1"


# ---------------------------------------------------------------------------
# The .form-input::placeholder case needs its ancestor's *pseudo-element*
# declaration read directly rather than through find_block()/declared() on
# the input itself -- ::placeholder is its own rule in admin.css.
# ---------------------------------------------------------------------------
def test_the_placeholder_check_reads_the_pseudo_element_rule():
    """Guards the ADMIN_PAIRS entry above against silently resolving the
    *input's* text colour instead of the placeholder's -- they are different
    rules (.form-input sets --text-primary; .form-input::placeholder sets
    --text-muted) and a selector typo would make this check pass for the
    wrong reason."""
    block = find_block(ADMIN_CSS_TEXT, ".form-input::placeholder")
    assert var_ref(declared(block, "color")) == "--text-muted"


# ===========================================================================
# Guards that can actually fail
#
# Same reasoning as test_error_pages_inline_styles.py's
# test_the_missing_class_check_can_actually_find_one and
# test_admin_inline_styles.py's test_the_check_can_actually_find_a_missing_
# class: a check that has only ever been seen passing is indistinguishable
# from one whose extractor is silently broken.
# ===========================================================================
def test_the_contrast_arithmetic_can_actually_fail():
    """Proves the formula finds a real failure when handed one, not just a
    passing one: dark's --status-healthy (#5AD69A, chosen for a dark
    surface) on light's --status-healthy-bg tint (#E3F4EA) is the exact
    wrong-theme pairing status_healthy_light_reverts_to_the_dark_shade
    plants below -- see tokens.css for why each theme needs its own step of
    the green ramp."""
    assert contrast_ratio("#5AD69A", "#E3F4EA") < 4.5


def test_text_secondary_resolves_to_each_themes_own_shade():
    """--text-muted has no consumer of its own (grep style.css -- nothing
    reads it): it is a plain alias of --text-secondary in both themes (see
    tokens.css's LIGHT/DARK blocks). The meaningful fact for this palette is
    that --text-secondary -- consumed everywhere from .nav-link to
    .footer-content -- resolves to each theme's OWN step of the grey ramp,
    never the other theme's, which is exactly what
    text_secondary_light/dark_reverts_to_the_other_themes_shade below
    mutate away."""
    assert resolved_hex(LIGHT, "--text-secondary") != resolved_hex(DARK, "--text-secondary")
    assert resolved_hex(LIGHT, "--text-muted") == resolved_hex(LIGHT, "--text-secondary")
    assert resolved_hex(DARK, "--text-muted") == resolved_hex(DARK, "--text-secondary")


def test_white_on_accent_primary_would_fail_in_dark_and_admin():
    """White text is not used on a solid --accent-primary fill anywhere any
    more (see --text-on-accent's consumers), but the number itself -- proving
    why -- must still hold: in the public dark theme, and in the admin
    console's own dark state, which resolves --accent-primary through that
    same shared layer now that the admin surface sets no colour of its own."""
    assert contrast_ratio("#FFFFFF", resolved_hex(DARK, "--accent-primary")) < 4.5
    assert contrast_ratio("#FFFFFF", resolved_hex(ADMIN_DARK, "--accent-primary")) < 4.5


# ===========================================================================
# Mutation testing (static half)
#
# Same shape as test_admin_js_escaping.py's MUTATIONS table: (name, old, new,
# must_fail). Each mutation is applied to a copy of the real file text, run
# back through the same builder/checker functions the real suite uses, and
# must turn at least the named check red. failed_ids is drawn from all three
# check tables -- public, token-level and admin -- since a token-only pair
# (--border-strong's, or the disk meter's) never appears in a selector-level
# PUBLIC_CHECKS id at all.
# ===========================================================================
TOKEN_MUTATIONS = [
    (
        # --text-muted has no consumer of its own (see
        # test_text_secondary_resolves_to_each_themes_own_shade), so the grey
        # text this guards is --text-secondary's.
        "text_secondary_light_reverts_to_the_other_themes_shade",
        "--text-secondary: var(--c-graphite-700);",
        "--text-secondary: var(--c-graphite-400);",
        ".mirror-description [light]",
    ),
    (
        # Also covers header_ambient_background()'s keying on the theme
        # label: this mutation's .nav-link [dark] must be scored against the
        # dark header, where it is 2.67:1 and fails; scored against the light
        # one it would read 4.62:1 and pass -- see
        # test_header_ambient_background_uses_the_dark_selector_for_a_
        # copied_dict above.
        "text_secondary_dark_reverts_to_the_other_themes_shade",
        "--text-secondary: var(--c-graphite-400);",
        "--text-secondary: var(--c-graphite-700);",
        ".nav-link [dark]",
    ),
    (
        # Targets the shared DARK line, not a LEGACY ADMIN one -- that block
        # is gone, and admin.css now reads this same token (spec section 7),
        # so a mutation here reaches both the public token pair and every
        # admin fill that consumes --text-on-accent.
        "text_on_accent_reverts_to_white",
        "--text-on-accent: var(--c-red-975);",
        "--text-on-accent: #FFFFFF;",
        None,  # asserted separately: this breaks an ADMIN_CHECKS id, checked below
    ),
    (
        # --status-error-text is retired (spec section 7): admin.css now
        # reads --status-error directly for the error badge and
        # .log-pre-error, the same shared token status_error_light_reverts_
        # to_the_dark_shade below already mutates for LIGHT. This targets the
        # DARK line instead, so both mutations stay distinct and each still
        # bites a real, different rendering.
        "status_error_text_reverts_to_status_error",
        "--status-error: var(--c-red-300);",
        "--status-error: var(--c-red-650);",
        None,  # breaks an ADMIN_CHECKS id, checked below
    ),
    (
        "status_healthy_light_reverts_to_the_dark_shade",
        "--status-healthy: var(--c-green-700);",
        "--status-healthy: var(--c-green-400);",
        None,  # breaks the pill, the dot and both token pairs at once, checked below
    ),
    (
        "status_syncing_light_reverts_to_the_dark_shade",
        "--status-syncing: var(--c-amber-800);",
        "--status-syncing: var(--c-amber-400);",
        '.pill[data-state="syncing"] [light]',
    ),
    (
        "status_error_light_reverts_to_the_dark_shade",
        "--status-error: var(--c-red-650);",
        "--status-error: var(--c-red-300);",
        '.pill[data-state="error"] [light]',
    ),
    (
        # The background side of a pill pair; every other entry here moves a
        # foreground. The light tint taking the dark theme's step must fail
        # the pill that sits on it, so a pill pair that read some other
        # surface instead of its own tint cannot pass unnoticed.
        "status_syncing_bg_light_reverts_to_the_dark_tint",
        "--status-syncing-bg: var(--c-amber-50);",
        "--status-syncing-bg: var(--c-amber-925);",
        '.pill[data-state="syncing"] [light]',
    ),
    (
        # --border-strong has no colour/background consumer in style.css
        # (only a border-color:, which declared()/declared_background()
        # never scan) -- this can only ever be caught at the token level.
        "border_strong_light_reverts_to_a_lighter_step",
        "--border-strong: var(--c-graphite-500);",
        "--border-strong: var(--c-graphite-400);",
        "--border-strong on --bg-card [light]",
    ),
    (
        "stream_line_dark_reverts_to_a_lighter_step",
        "--stream-line: var(--c-graphite-650);",
        "--stream-line: var(--c-graphite-700);",
        None,  # breaks the selector-level stream-line pair and its token pair, checked below
    ),
]


@pytest.mark.parametrize(
    "name,old,new,must_fail", TOKEN_MUTATIONS, ids=[m[0] for m in TOKEN_MUTATIONS]
)
def test_tokens_css_mutation_is_caught(name, old, new, must_fail):
    assert TOKENS_TEXT.count(old) == 1, (
        f"mutation {name!r} no longer matches tokens.css exactly once "
        f"(found {TOKENS_TEXT.count(old)}). Update the mutation, do not delete it."
    )
    mutated_text = TOKENS_TEXT.replace(old, new)
    light, dark, admin_light, admin_dark = build_themes(mutated_text)

    public_results = compute_public_checks(STYLE_CSS_TEXT, {"light": light, "dark": dark})
    token_results = compute_token_checks({"light": light, "dark": dark})
    admin_results = compute_admin_checks(ADMIN_CSS_TEXT, {"light": admin_light, "dark": admin_dark})
    failed_ids = {
        cid
        for cid, ratio, min_ratio, *_ in public_results + token_results + admin_results
        if ratio < min_ratio
    }

    assert failed_ids, f"mutation {name!r} changed a live token and nothing failed"
    if must_fail is not None:
        assert must_fail in failed_ids, (
            f"mutation {name!r} was expected to fail {must_fail!r}, but the "
            f"failures were {sorted(failed_ids)}"
        )


def test_text_on_accent_mutation_breaks_an_admin_fill():
    """The two token mutations above that pass must_fail=None still have to
    break *something* concrete -- named here instead of folded into the
    parametrised case so a failure points at a specific, checkable claim
    rather than "some id or other went red". Only .user-avatar and
    .btn-primary read --text-on-accent (admin.css); .nav-item.active reads
    --text-primary and .btn-danger reads --status-error now, so mutating this
    one token no longer touches either of those two."""
    mutated_text = TOKENS_TEXT.replace(
        "--text-on-accent: var(--c-red-975);", "--text-on-accent: #FFFFFF;"
    )
    _, _, _, admin_dark = build_themes(mutated_text)
    results = {
        cid: ratio for cid, ratio, *_ in compute_admin_checks(ADMIN_CSS_TEXT, {"dark": admin_dark})
    }
    assert results[".user-avatar [dark]"] < 4.5
    assert results[".btn-primary [dark]"] < 4.5


def test_status_error_text_mutation_breaks_the_error_badge():
    """--status-error-text is retired; admin.css's error badge and
    .log-pre-error now read --status-error directly (spec section 7), so this
    mutates that shared DARK line -- see the TOKEN_MUTATIONS entry above."""
    mutated_text = TOKENS_TEXT.replace(
        "--status-error: var(--c-red-300);", "--status-error: var(--c-red-650);"
    )
    _, _, _, admin_dark = build_themes(mutated_text)
    results = {
        cid: ratio for cid, ratio, *_ in compute_admin_checks(ADMIN_CSS_TEXT, {"dark": admin_dark})
    }
    assert results[".status-badge.error [dark]"] < 4.5
    assert results[".status-badge.failed [dark]"] < 4.5
    assert results[".log-pre-error [dark]"] < 4.5


def test_status_healthy_mutation_breaks_the_pill_the_dot_and_both_tokens():
    """--status-healthy backs .pill[data-state="online"] (text on the tint),
    .status-card[data-state="online"] .status-dot (a fill on --bg-card) and
    two TOKEN_PAIRS rows at once -- darkening it for one and not the others
    was never on the table, so one mutation must break all four."""
    mutated_text = TOKENS_TEXT.replace(
        "--status-healthy: var(--c-green-700);", "--status-healthy: var(--c-green-400);"
    )
    light, dark, _, _ = build_themes(mutated_text)
    themes = {"light": light, "dark": dark}
    results = {cid: ratio for cid, ratio, *_ in compute_public_checks(STYLE_CSS_TEXT, themes)}
    tokens = {cid: ratio for cid, ratio, *_ in compute_token_checks(themes)}
    assert results['.pill[data-state="online"] [light]'] < 4.5
    assert results['.status-card[data-state="online"] .status-dot [light]'] < 3.0
    assert tokens["--status-healthy on --status-healthy-bg [light]"] < 4.5
    assert tokens["--status-healthy on --bg-card [light]"] < 3.0


def test_stream_line_mutation_breaks_the_selector_and_the_token_pair():
    """--stream-line is read both as a component rule (the online stream's
    solid line) and, independently, at the token level (section 9's list) --
    a fix at either layer could otherwise mask a regression at the other, so
    one mutation must break both."""
    mutated_text = TOKENS_TEXT.replace(
        "--stream-line: var(--c-graphite-650);", "--stream-line: var(--c-graphite-700);"
    )
    light, dark, _, _ = build_themes(mutated_text)
    themes = {"light": light, "dark": dark}
    results = {cid: ratio for cid, ratio, *_ in compute_public_checks(STYLE_CSS_TEXT, themes)}
    tokens = {cid: ratio for cid, ratio, *_ in compute_token_checks(themes)}
    assert results['.stream[data-state="online"] .stream-line::before [dark]'] < 3.0
    assert tokens["--stream-line on --bg-card [dark]"] < 3.0


def test_status_syncing_bg_mutation_breaks_the_pill_and_its_token_pair():
    """--status-syncing-bg is read by .pill[data-state="syncing"] (the
    must_fail the parametrised case above names) and, independently, by the
    --status-syncing on --status-syncing-bg token pair: one mutation of the
    tint must break both, so a fix at either layer cannot mask the other."""
    mutated_text = TOKENS_TEXT.replace(
        "--status-syncing-bg: var(--c-amber-50);", "--status-syncing-bg: var(--c-amber-925);"
    )
    light, dark, _, _ = build_themes(mutated_text)
    themes = {"light": light, "dark": dark}
    results = {cid: ratio for cid, ratio, *_ in compute_public_checks(STYLE_CSS_TEXT, themes)}
    tokens = {cid: ratio for cid, ratio, *_ in compute_token_checks(themes)}
    assert results['.pill[data-state="syncing"] [light]'] < 4.5
    assert tokens["--status-syncing on --status-syncing-bg [light]"] < 4.5


CSS_MUTATIONS = [
    (
        # A slip this palette does not make harmless: painting the online
        # sync-stream's line with the plain hairline --border-color instead
        # of the purpose-built --stream-line token (a very plausible "they're
        # both just greys" swap) fails the 3:1 indicator floor in both
        # themes. (--accent-primary, by contrast, clears the header and every
        # card and tinted surface on its own -- style.css's .nav-admin comment
        # -- so no swap to it is worth a mutation here.)
        "stream_line_online_reverts_to_the_plain_border_colour",
        STYLE_CSS,
        "STYLE",
        "height: 1.5px;\n    background: var(--stream-line);",
        "height: 1.5px;\n    background: var(--border-color);",
        '.stream[data-state="online"] .stream-line::before [light]',
    ),
    (
        "btn_primary_public_reverts_to_white_text",
        STYLE_CSS,
        "STYLE",
        "background: var(--accent-primary);\n    border-color: transparent;\n    color: var(--text-on-accent);",
        "background: var(--accent-primary);\n    border-color: transparent;\n    color: white;",
        ".btn-primary [dark]",
    ),
    (
        # A component-file edit, not a token edit: reverts just this one
        # rule's `color`, independent of
        # test_status_error_text_mutation_breaks_the_error_badge above (which
        # mutates a shared token instead). Both must be caught; a fix at
        # either layer could otherwise mask a regression at the other.
        # #6B7280 -- a plausible, unremarkable muted grey (the kind of colour
        # left behind by copying the neutral .status-badge rule and
        # forgetting to retint it) -- is not one of admin.css's own tokens, so
        # planting it cannot pass for a reason unrelated to this rule; it is
        # 3.98:1 against --status-error-bg in light and 3.55:1 in dark,
        # confirmed by hand against tokens.css's resolved values, below 4.5:1
        # in both.
        "status_badge_error_reverts_color_to_a_plausible_low_contrast_grey",
        ADMIN_CSS,
        "ADMIN",
        ".status-badge.error {\n    color: var(--status-error);\n"
        "    background: var(--status-error-bg);\n}",
        ".status-badge.error {\n    color: #6B7280;\n" "    background: var(--status-error-bg);\n}",
        ".status-badge.error [light]",
    ),
    (
        # Same shape and the same grey, for the health-checks card's
        # "incomplete" badge: 4.02:1 against --status-incomplete-bg in light,
        # 3.42:1 in dark.
        "status_badge_health_incomplete_reverts_color_to_a_plausible_low_contrast_grey",
        ADMIN_CSS,
        "ADMIN",
        ".status-badge.health-incomplete {\n    color: var(--status-incomplete);\n"
        "    background: var(--status-incomplete-bg);\n}",
        ".status-badge.health-incomplete {\n    color: #6B7280;\n"
        "    background: var(--status-incomplete-bg);\n}",
        ".status-badge.health-incomplete [light]",
    ),
    (
        # Same shape, for the archive-inventory table's informational tag
        # variant (Newest / Latest-in-major / Pre-release) and the job
        # "pending" pill: 4.12:1 against --status-info-bg in light, 3.28:1 in
        # dark.
        "status_badge_info_reverts_color_to_a_plausible_low_contrast_grey",
        ADMIN_CSS,
        "ADMIN",
        ".status-badge.info {\n    color: var(--status-info);\n"
        "    background: var(--status-info-bg);\n}",
        ".status-badge.info {\n    color: #6B7280;\n" "    background: var(--status-info-bg);\n}",
        ".status-badge.info [light]",
    ),
    (
        # Same shape, for the "At risk" pill: 4.28:1 against
        # --status-syncing-bg in light, 3.25:1 in dark.
        "status_badge_at_risk_reverts_color_to_a_plausible_low_contrast_grey",
        ADMIN_CSS,
        "ADMIN",
        ".status-badge.at-risk {\n    color: var(--status-syncing);\n"
        "    background: var(--status-syncing-bg);\n}",
        ".status-badge.at-risk {\n    color: #6B7280;\n"
        "    background: var(--status-syncing-bg);\n}",
        ".status-badge.at-risk [light]",
    ),
]


@pytest.mark.parametrize(
    "name,path,which,old,new,must_fail", CSS_MUTATIONS, ids=[m[0] for m in CSS_MUTATIONS]
)
def test_component_css_mutation_is_caught(name, path, which, old, new, must_fail):
    source = path.read_text(encoding="utf-8")
    assert source.count(old) == 1, (
        f"mutation {name!r} no longer matches {path.name} exactly once "
        f"(found {source.count(old)}). Update the mutation, do not delete it."
    )
    mutated = source.replace(old, new)

    if which == "STYLE":
        results = compute_public_checks(mutated, {"light": LIGHT, "dark": DARK})
    else:
        results = compute_admin_checks(mutated, {"light": ADMIN_LIGHT, "dark": ADMIN_DARK})

    failed_ids = {cid for cid, ratio, min_ratio, *_ in results if ratio < min_ratio}
    assert failed_ids, f"mutation {name!r} changed a live rule and nothing failed"
    assert must_fail in failed_ids, (
        f"mutation {name!r} was expected to fail {must_fail!r}, but the "
        f"failures were {sorted(failed_ids)}"
    )


def test_stream_line_online_css_mutation_also_fails_in_dark():
    """The CSS_MUTATIONS entry above only names the [light] id (must_fail
    takes one); --border-color is a near-invisible hairline in both themes,
    so this checks the other one explicitly rather than leaving it
    unproven."""
    source = STYLE_CSS.read_text(encoding="utf-8")
    old = "height: 1.5px;\n    background: var(--stream-line);"
    new = "height: 1.5px;\n    background: var(--border-color);"
    mutated = source.replace(old, new)
    results = {
        cid: ratio
        for cid, ratio, *_ in compute_public_checks(mutated, {"light": LIGHT, "dark": DARK})
    }
    assert results['.stream[data-state="online"] .stream-line::before [dark]'] < 3.0


# ===========================================================================
# DYNAMIC: real headless Chrome, real getComputedStyle, real :hover
# ===========================================================================
NODE = shutil.which("node")

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
]


def find_chrome():
    for candidate in CHROME_CANDIDATES:
        if "/" in candidate:
            if pathlib.Path(candidate).exists():
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    return None


CHROME = find_chrome()
requires_browser = pytest.mark.skipif(
    NODE is None or CHROME is None,
    reason=f"needs node and Chrome (node={bool(NODE)}, chrome={bool(CHROME)})",
)


def run_contrast_harness(docroot, admin_js_path):
    proc = subprocess.run(
        [NODE, str(HARNESS), str(docroot), str(admin_js_path), CHROME],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, (
        f"contrast harness failed (rc={proc.returncode})\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def measured():
    return run_contrast_harness(REPO_ROOT / "frontend" / "public", ADMIN_JS)


_RGB_RE = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)")


def _rgb_string_to_hex(value):
    m = _RGB_RE.fullmatch(value.strip())
    assert m, f"not an rgb()/rgba() string: {value!r}"
    r, g, b = (round(float(m.group(i))) for i in (1, 2, 3))
    return "#%02X%02X%02X" % (r, g, b)


def _measured_ratio(measurement, page_bg_hex):
    """A harness measurement is {color, backgroundColor}, both rgb()/rgba()
    strings from getComputedStyle. backgroundColor keeps its alpha as
    declared (getComputedStyle never composites); this composites it over
    the resolved page background exactly the way header_ambient_background()
    does for the static half, so a translucent .header reads correctly.

    The foreground gets no such treatment: every probed text colour, dot and
    line is an opaque token, so a translucent one means the probe read an
    element the expected rule never painted -- an unmatched ::before reads
    rgba(0, 0, 0, 0), which dropping the alpha would score as black, a
    false 21:1 against a white card."""
    assert "error" not in measurement, f"harness could not measure this element: {measurement}"
    fg = _RGB_RE.fullmatch(measurement["color"].strip())
    assert fg, f"not an rgb()/rgba() string: {measurement['color']!r}"
    fg_alpha = float(fg.group(4)) if fg.group(4) is not None else 1.0
    assert fg_alpha >= 1.0, (
        f"the measured foreground {measurement['color']!r} is translucent (alpha "
        f"{fg_alpha:g}), so no contrast ratio can be read from it: the rule this "
        f"probe expects did not paint the element"
    )
    fg_hex = _rgb_string_to_hex(measurement["color"])
    m = _RGB_RE.fullmatch(measurement["backgroundColor"].strip())
    r, g, b = (round(float(m.group(i))) for i in (1, 2, 3))
    alpha = float(m.group(4)) if m.group(4) is not None else 1.0
    bg_hex = "#%02X%02X%02X" % (r, g, b)
    if alpha < 1.0:
        bg_hex = composite(bg_hex, alpha, page_bg_hex)
    return contrast_ratio(fg_hex, bg_hex)


# (probe_id, theme_label, min_ratio) -- a hand-maintained copy of
# PUBLIC_PROBES in contrast_harness.mjs, pinned in step by
# test_dynamic_probe_list_matches_the_harness below. Every id is measured in
# both themes; the four ids the /api/ stub cannot reach on its own (the
# neutral pill, and the online, syncing and neutral status-dot) are reached
# by the harness setting data-state itself, not by relying on which state the
# stub happens to produce -- see contrast_harness.mjs's docstring.
# fmt: off
DYNAMIC_PUBLIC_CHECKS = [
    ("body", "light", 4.5), ("body", "dark", 4.5),
    (".nav-link", "light", 4.5), (".nav-link", "dark", 4.5),
    (".nav-link:hover", "light", 4.5), (".nav-link:hover", "dark", 4.5),
    (".nav-admin", "light", 4.5), (".nav-admin", "dark", 4.5),
    (".stat-label", "light", 4.5), (".stat-label", "dark", 4.5),
    (".mirror-description", "light", 4.5), (".mirror-description", "dark", 4.5),
    (".access-label", "light", 4.5), (".access-label", "dark", 4.5),
    (".btn-primary", "light", 4.5), (".btn-primary", "dark", 4.5),
    (".btn-secondary:hover", "light", 4.5), (".btn-secondary:hover", "dark", 4.5),
    (".footer-content p", "light", 4.5), (".footer-content p", "dark", 4.5),
    (".footer-content a", "light", 4.5), (".footer-content a", "dark", 4.5),
    (".about-text a", "light", 4.5), (".about-text a", "dark", 4.5),
    (".footer-version", "light", 4.5), (".footer-version", "dark", 4.5),
    (".section-subtitle", "light", 4.5), (".section-subtitle", "dark", 4.5),
    (".toast", "light", 4.5), (".toast", "dark", 4.5),
    (".pill", "light", 4.5), (".pill", "dark", 4.5),
    ('.pill[data-state="online"]', "light", 4.5), ('.pill[data-state="online"]', "dark", 4.5),
    ('.pill[data-state="syncing"]', "light", 4.5), ('.pill[data-state="syncing"]', "dark", 4.5),
    ('.pill[data-state="error"]', "light", 4.5), ('.pill[data-state="error"]', "dark", 4.5),
    # UI indicators (WCAG 2.1 SC 1.4.11): 3:1, not 4.5:1.
    (".status-dot", "light", 3.0), (".status-dot", "dark", 3.0),
    ('.status-card[data-state="online"] .status-dot', "light", 3.0),
    ('.status-card[data-state="online"] .status-dot', "dark", 3.0),
    ('.status-card[data-state="syncing"] .status-dot', "light", 3.0),
    ('.status-card[data-state="syncing"] .status-dot', "dark", 3.0),
    ('.status-card[data-state="error"] .status-dot', "light", 3.0),
    ('.status-card[data-state="error"] .status-dot', "dark", 3.0),
    ('.stream[data-state="online"] .stream-line::before', "light", 3.0),
    ('.stream[data-state="online"] .stream-line::before', "dark", 3.0),
]
# fmt: on


@requires_browser
@pytest.mark.parametrize(
    "probe_id,theme_label,min_ratio",
    DYNAMIC_PUBLIC_CHECKS,
    ids=[f"{p} [{t}]" for p, t, _ in DYNAMIC_PUBLIC_CHECKS],
)
def test_public_site_contrast_in_a_real_browser(measured, probe_id, theme_label, min_ratio):
    page_bg = resolved_hex(LIGHT if theme_label == "light" else DARK, "--bg-primary")
    measurement = measured["public"][theme_label][probe_id]
    ratio = _measured_ratio(measurement, page_bg)
    assert ratio >= min_ratio, (
        f"{probe_id} [{theme_label}]: real browser measured {measurement}, "
        f"contrast {ratio:.2f}:1, needs >= {min_ratio}:1"
    )


# (probe_id, theme_label, min_ratio), the admin equivalent of
# DYNAMIC_PUBLIC_CHECKS above: every probe is measured in both
# data-surface="admin" (light) and data-theme="dark" data-surface="admin"
# (dark) -- see contrast_harness.mjs's ADMIN_PROBES and its two-fixture-page
# docstring. The three new entries cover a job-status pill, the disk meter's
# warning-band fill and the theme toggle -- the components spec 6.1 and 4.8
# added that the pre-redesign console never had.
# fmt: off
DYNAMIC_ADMIN_CHECKS = [
    (".login-subtitle", "light", 4.5), (".login-subtitle", "dark", 4.5),
    (".btn-primary", "light", 4.5), (".btn-primary", "dark", 4.5),
    (".nav-item.active", "light", 4.5), (".nav-item.active", "dark", 4.5),
    (".user-avatar", "light", 4.5), (".user-avatar", "dark", 4.5),
    (".user-role", "light", 4.5), (".user-role", "dark", 4.5),
    (".nav-section-title", "light", 4.5), (".nav-section-title", "dark", 4.5),
    (".status-badge.disabled", "light", 4.5), (".status-badge.disabled", "dark", 4.5),
    (".status-badge.active", "light", 4.5), (".status-badge.active", "dark", 4.5),
    ("th", "light", 4.5), ("th", "dark", 4.5),
    (".u-text-muted", "light", 4.5), (".u-text-muted", "dark", 4.5),
    (".status-badge.error", "light", 4.5), (".status-badge.error", "dark", 4.5),
    (".status-badge.syncing", "light", 4.5), (".status-badge.syncing", "dark", 4.5),
    (".status-badge.completed", "light", 4.5), (".status-badge.completed", "dark", 4.5),
    (".theme-toggle", "light", 4.5), (".theme-toggle", "dark", 4.5),
    (".form-input::placeholder", "light", 4.5), (".form-input::placeholder", "dark", 4.5),
    # A UI indicator (WCAG 2.1 SC 1.4.11), not text: 3:1, not 4.5:1.
    (".meter-fill.is-warn", "light", 3.0), (".meter-fill.is-warn", "dark", 3.0),
]
# fmt: on


@requires_browser
@pytest.mark.parametrize(
    "probe_id,theme_label,min_ratio",
    DYNAMIC_ADMIN_CHECKS,
    ids=[f"{p} [{t}]" for p, t, _ in DYNAMIC_ADMIN_CHECKS],
)
def test_admin_panel_contrast_in_a_real_browser(measured, probe_id, theme_label, min_ratio):
    page_bg = resolved_hex(ADMIN_LIGHT if theme_label == "light" else ADMIN_DARK, "--bg-primary")
    measurement = measured["admin"][theme_label][probe_id]
    ratio = _measured_ratio(measurement, page_bg)
    assert ratio >= min_ratio, (
        f"{probe_id} [{theme_label}]: real browser measured {measurement}, "
        f"contrast {ratio:.2f}:1, needs >= {min_ratio}:1"
    )


@requires_browser
def test_dynamic_probe_list_matches_the_harness():
    """The two probe id lists above are a hand-maintained copy of
    PUBLIC_PROBES/ADMIN_PROBES in contrast_harness.mjs. Pins them together the
    same way test_admin_inline_styles.py pins its STYLEHEETS list against
    admin/index.html's actual <link> tags -- so a probe added to one and not
    the other fails loudly here instead of silently measuring nothing.
    ADMIN_PROBES is a single, theme-independent list run once per theme (the
    harness re-measures the same probes against a fresh light and a fresh
    dark fixture page), so its id set is compared against DYNAMIC_ADMIN_CHECKS
    with the theme label dropped, not doubled."""
    harness_source = HARNESS.read_text(encoding="utf-8")
    public_block = re.search(r"const PUBLIC_PROBES = \[(.*?)\n\];", harness_source, re.S)
    admin_block = re.search(r"const ADMIN_PROBES = \[(.*?)\n\];", harness_source, re.S)
    assert public_block and admin_block

    harness_public_ids = set(re.findall(r"id:\s*'([^']+)'", public_block.group(1)))
    harness_admin_ids = set(re.findall(r"id:\s*'([^']+)'", admin_block.group(1)))

    test_public_ids = {p for p, _, _ in DYNAMIC_PUBLIC_CHECKS}
    test_admin_ids = {p for p, _, _ in DYNAMIC_ADMIN_CHECKS} | {".form-input::placeholder"}

    assert test_public_ids == harness_public_ids, (
        f"public probe ids differ: test has {test_public_ids - harness_public_ids} extra, "
        f"harness has {harness_public_ids - test_public_ids} extra"
    )
    # The harness measures placeholder separately from ADMIN_PROBES (it needs
    # the two-argument getComputedStyle form); admin_block therefore will not
    # contain it, which is expected rather than a drift.
    assert test_admin_ids - {".form-input::placeholder"} == harness_admin_ids, (
        f"admin probe ids differ: test has "
        f"{(test_admin_ids - {'.form-input::placeholder'}) - harness_admin_ids} extra, "
        f"harness has {harness_admin_ids - test_admin_ids} extra"
    )


@requires_browser
def test_harness_detects_a_reintroduced_low_contrast_fill(tmp_path):
    """Negative control for the dynamic half, same shape as
    test_public_page_csp.py's test_harness_detects_a_reintroduced_inline_
    handler: plant the original bug in a copy of the real docroot, rerun the
    real harness, and require it to see a real browser render white on
    accent-primary rather than merely trusting the source diff.

    The bug lives in admin.css (.btn-primary's `color`), not admin.js -- the
    harness links the real admin.css into its fixture page, so the docroot
    served to it, not the admin.js path, is what needs mutating. Checked in
    dark only: white on light's --accent-primary is 5.63:1 and genuinely
    passes (the same asymmetry test_white_on_accent_primary_would_fail_in_
    dark_and_admin and the public btn_primary_public_reverts_to_white_text
    mutation both already only claim for [dark])."""
    docroot = tmp_path / "public"
    shutil.copytree(REPO_ROOT / "frontend" / "public", docroot)
    admin_css_copy = docroot / "admin" / "css" / "admin.css"

    source = admin_css_copy.read_text(encoding="utf-8")
    old = "background: var(--accent-primary);\n    color: var(--text-on-accent);\n}"
    new = "background: var(--accent-primary);\n    color: white;\n}"
    assert (
        source.count(old) == 1
    ), "admin.css .btn-primary rule no longer matches; update the control"
    admin_css_copy.write_text(source.replace(old, new), encoding="utf-8")

    result = run_contrast_harness(docroot, ADMIN_JS)
    ratio = _measured_ratio(
        result["admin"]["dark"][".btn-primary"], resolved_hex(ADMIN_DARK, "--bg-primary")
    )
    assert ratio < 4.5, (
        f"planting color: white back into admin.css's .btn-primary did not make a "
        f"real browser render a failing ratio (measured {ratio:.2f}:1) -- the "
        f"harness is not actually measuring what admin.css renders"
    )


@requires_browser
def test_harness_detects_a_low_contrast_pill_on_the_public_page(tmp_path):
    """The public half's negative control, the same shape as the admin one
    above: plant a low-contrast text colour on the online pill in a copy of
    the docroot's style.css, rerun the real harness, and require a real
    browser to render a failing ratio for that probe in both themes.
    #5E8A6E, a plausible muted green, is 3.45:1 on the light online tint and
    3.90:1 on the dark one."""
    docroot = tmp_path / "public"
    shutil.copytree(REPO_ROOT / "frontend" / "public", docroot)
    style_css_copy = docroot / "css" / "style.css"

    source = style_css_copy.read_text(encoding="utf-8")
    old = '.pill[data-state="online"] {\n    color: var(--status-healthy);'
    new = '.pill[data-state="online"] {\n    color: #5E8A6E;'
    assert (
        source.count(old) == 1
    ), "style.css's online pill rule no longer matches; update the control"
    style_css_copy.write_text(source.replace(old, new), encoding="utf-8")

    result = run_contrast_harness(docroot, ADMIN_JS)
    for theme_label, theme in (("light", LIGHT), ("dark", DARK)):
        measurement = result["public"][theme_label]['.pill[data-state="online"]']
        ratio = _measured_ratio(measurement, resolved_hex(theme, "--bg-primary"))
        assert ratio < 4.5, (
            f"planting color: #5E8A6E on style.css's online pill did not make a real "
            f"browser render a failing ratio in {theme_label} (measured {ratio:.2f}:1) "
            f"-- the harness is not actually measuring what style.css renders"
        )


@requires_browser
def test_harness_reports_an_uncaught_js_error_on_the_public_page(tmp_path):
    """Negative control for the DevTools exception guard added to
    contrast_harness.mjs: plant a synchronous throw where main.js's
    DOMContentLoaded handler runs, rerun the real harness against a copy of
    the docroot, and require it to fail loudly (not hang, not silently
    return a partial measurement) instead of merely trusting that
    Runtime.exceptionThrown is wired up correctly."""
    docroot = tmp_path / "public"
    shutil.copytree(REPO_ROOT / "frontend" / "public", docroot)
    main_js_copy = docroot / "js" / "main.js"

    source = main_js_copy.read_text(encoding="utf-8")
    old = "document.addEventListener('DOMContentLoaded', () => {\n    ThemeManager.init();"
    new = (
        "document.addEventListener('DOMContentLoaded', () => {\n"
        "    throw new Error('planted for test_harness_reports_an_uncaught_js_error_on_the_public_page');"
        "\n    ThemeManager.init();"
    )
    assert (
        source.count(old) == 1
    ), "main.js's DOMContentLoaded handler no longer matches; update the control"
    main_js_copy.write_text(source.replace(old, new), encoding="utf-8")

    proc = subprocess.run(
        [NODE, str(HARNESS), str(docroot), str(ADMIN_JS), CHROME],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode != 0, (
        "planting a synchronous throw in main.js's DOMContentLoaded handler "
        "did not make the harness fail -- it is not actually watching for "
        f"uncaught JS errors on the public page\nstdout:\n{proc.stdout}"
    )
    assert (
        "planted for test_harness_reports_an_uncaught_js_error_on_the_public_page" in proc.stderr
    ), f"the harness failed, but not with the planted error's message:\n{proc.stderr}"
