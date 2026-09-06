"""WCAG 2.1 AA contrast for the public site and the admin panel.

Two failing pairs were carried in this project's notes for a while
(--text-muted on --bg-tertiary, white on --accent-primary), plus a third found
while bringing the error pages to AA (--accent-primary on --bg-primary passes
the 3:1 large-text bar but fails the 4.5:1 body-text bar -- same token, two
requirements depending on where it renders). Measuring the actual rendered
pairs turned up a larger set than those three: --text-muted fails against
every surface background it is actually used on, not just --bg-tertiary; the
brand gradient fails under white text at one end or the other in every theme;
and the admin surface has its own version of the same shape wherever
--status-error is asked to render as text rather than a small dot or a
border. See tokens.css and the component stylesheets for the fix on each.

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
not just every value a token happens to hold.

DYNAMIC (skips without node/Chrome): shells out to
tests/js/contrast_harness.mjs, which drives real headless Chrome and reads
getComputedStyle for the same elements, including two genuine :hover states
dispatched as real mouse input. What the static half cannot see on its own:
whether the browser's actual cascade -- specificity, inheritance, a CSS
transition sampled mid-fade -- agrees with what a text-only parser assumed.
See that file's docstring for the rest of the trade-offs (most notably: it
reaches admin.js's markup by calling its page-renderer functions directly,
the same way tests/js/escaping_harness.mjs does, rather than driving the SPA
through a live backend).

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
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


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
# A tiny CSS reader: comment stripping, exact-selector block lookup,
# declaration lookup, and var() resolution against tokens.css's cascade.
#
# Deliberately not a general CSS parser -- just enough to answer "what does
# this exact selector declare for this exact property", the same scope
# test_error_pages_inline_styles.py's regexes keep to.
# ===========================================================================
_RULE_RE = re.compile(r"([^{}]+)\{([^}]*)\}")


def strip_css_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def find_block(css_text, selector):
    """The declaration body of the one rule whose selector, once stripped of
    surrounding whitespace, is exactly `selector` -- not a substring match,
    so `.nav-link` cannot accidentally match `.nav-link:hover` and a combined
    selector like `th,\\ntd` cannot accidentally match `th`."""
    css = strip_css_comments(css_text)
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
# can plant a literal like the original `color: white` and have the checker
# compute a real (failing) ratio for it, instead of tripping var_ref()'s
# assertion on a value that was never a token reference to begin with. No
# real, un-mutated rule in style.css/admin.css uses one of these any more --
# that is the change this whole file exists to pin.
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
    """Returns (light, dark, admin), each {token_name: raw value string}.

    Raw, not yet resolved through var() -- resolve()/resolved_hex() below walk
    the chain at lookup time using whichever of these three dicts is asked,
    so a token that is only overridden for one theme still resolves correctly
    through the layers under it (tokens.css's own layering rule: dark
    overrides light, admin overrides dark).
    """
    css = strip_css_comments(tokens_css_text)
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

    assert len(root_bodies) == 3, (
        f"expected 3 :root blocks (primitives, invariants, light theme), found {len(root_bodies)}"
    )
    assert dark_body is not None, 'no [data-theme="dark"] block found'
    assert admin_body is not None, 'no [data-surface="admin"] block found'

    light = {}
    for body in root_bodies:
        light.update(parse_custom_properties(body))

    dark = dict(light)
    dark.update(parse_custom_properties(dark_body))

    admin = dict(dark)
    admin.update(parse_custom_properties(admin_body))

    return light, dark, admin


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
LIGHT, DARK, ADMIN = build_themes(TOKENS_TEXT)


def test_light_dark_admin_actually_differ():
    """A guard against build_themes() silently returning the same dict three
    times, which would make every "checked in both themes" claim below
    meaningless."""
    assert resolved_hex(LIGHT, "--bg-primary") != resolved_hex(DARK, "--bg-primary")
    assert resolved_hex(DARK, "--accent-secondary") != resolved_hex(ADMIN, "--accent-secondary")


def test_gradient_is_not_a_resolvable_solid_colour():
    """--accent-gradient is a linear-gradient(), not a colour; resolved_hex()
    must reject it loudly rather than return something that looks like a
    hex string. Relied on by CSS_MUTATIONS below to keep a mutation's
    background deliberately untouched -- a mutation that put --accent-
    gradient back as a background is supposed to be unscoreable, not silently
    scored against one of its two stops."""
    with pytest.raises(AssertionError):
        resolved_hex(LIGHT, "--accent-gradient")


# ===========================================================================
# .header's own background is a literal translucent rgba(), not a
# var(--bg-*) token -- it needs the alpha for the sticky/blurred header
# effect. .nav-link and .nav-admin have no background of their own, so the
# backdrop they actually render against is that rgba() composited over
# whatever is behind the header: --bg-primary, the page background.
#
# Known simplification: the page also has a `.background-gradient` radial
# tint layered under the header. It is a faint (7-10% alpha) orange glow
# centred above the viewport, fading out by the time it reaches the header
# strip; ignoring it very slightly *warms* the effective backdrop this
# function computes, which is not the direction that would turn a passing
# ratio into a failing one for any of the (cool-neutral or already
# wide-margin) checks that use it. Not modelled, for that reason.
# ===========================================================================
def header_ambient_background(style_css_text, theme):
    selector = '[data-theme="dark"] .header' if theme is DARK else ".header"
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


# ===========================================================================
# The pairs the public site actually renders (style.css)
#
# Each entry: (id, fg_selector, fg_prop, bg_source, min_ratio).
# bg_source is either ("own", prop) for the same block, ("parent", selector)
# for a named ancestor rule's background, or ("header",) for the special case
# above. Checked in both light and dark, since main.js can set either on the
# public site.
# ===========================================================================
PUBLIC_PAIRS = [
    ("body text", "body", "color", ("own",), 4.5),
    (".nav-link", ".nav-link", "color", ("header",), 4.5),
    (".nav-link:hover", ".nav-link:hover", "color", ("own",), 4.5),
    (".nav-admin", ".nav-admin", "color", ("header",), 4.5),
    (".stat-label", ".stat-label", "color", ("parent", ".stat-card"), 4.5),
    (".mirror-status", ".mirror-status", "color", ("parent", ".mirror-card"), 4.5),
    (".detail-label", ".detail-label", "color", ("parent", ".mirror-details"), 4.5),
    (".btn-primary", ".btn-primary", "color", ("own",), 4.5),
    (".btn-secondary:hover", ".btn-secondary:hover", "color", ("own",), 4.5),
    (".footer-content p", ".footer-content p", "color", ("parent", ".footer"), 4.5),
    (".method-card p", ".method-card p", "color", ("parent", ".method-card"), 4.5),
]


def compute_public_checks(style_css_text, themes):
    """themes: {label: theme_dict}. Returns [(check_id, ratio, min_ratio)]."""
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
            elif kind == "header":
                bg_hex = header_ambient_background(style_css_text, theme)
            else:  # pragma: no cover - guards a typo in PUBLIC_PAIRS itself
                raise AssertionError(f"unknown bg_source kind {kind!r}")

            ratio = contrast_ratio(fg_hex, bg_hex)
            results.append((f"{check_id} [{label}]", ratio, min_ratio, fg_hex, bg_hex))
    return results


# The large-text exemption: .gradient-text paints the 3rem/2.25rem hero
# heading with --accent-gradient via background-clip: text, so *both* stops
# render as the heading's own colour against --bg-primary, at the 3:1
# large-text bar rather than 4.5:1.
def compute_gradient_text_checks(tokens_css_text, themes):
    results = []
    for label, theme in themes.items():
        stops = re.findall(r"var\((--[\w-]+)\)", theme["--accent-gradient"])
        assert len(stops) == 2, (
            f"expected --accent-gradient to have exactly 2 var() stops, found {stops}"
        )
        bg_hex = resolved_hex(theme, "--bg-primary")
        for stop in stops:
            ratio = contrast_ratio(resolved_hex(theme, stop), bg_hex)
            results.append((f".gradient-text {stop} [{label}]", ratio, 3.0, None, None))
    return results


STYLE_CSS_TEXT = STYLE_CSS.read_text(encoding="utf-8")
PUBLIC_CHECKS = compute_public_checks(STYLE_CSS_TEXT, {"light": LIGHT, "dark": DARK})
GRADIENT_CHECKS = compute_gradient_text_checks(TOKENS_TEXT, {"light": LIGHT, "dark": DARK})


@pytest.mark.parametrize(
    "check_id,ratio,min_ratio,fg_hex,bg_hex",
    PUBLIC_CHECKS,
    ids=[c[0] for c in PUBLIC_CHECKS],
)
def test_public_site_contrast(check_id, ratio, min_ratio, fg_hex, bg_hex):
    assert ratio >= min_ratio, (
        f"{check_id}: {fg_hex} on {bg_hex} is {ratio:.2f}:1, needs >= {min_ratio}:1"
    )


@pytest.mark.parametrize(
    "check_id,ratio,min_ratio,fg_hex,bg_hex",
    GRADIENT_CHECKS,
    ids=[c[0] for c in GRADIENT_CHECKS],
)
def test_gradient_text_large_text_contrast(check_id, ratio, min_ratio, fg_hex, bg_hex):
    assert ratio >= min_ratio, f"{check_id} is {ratio:.2f}:1, needs >= {min_ratio}:1 (large text)"


def test_footer_version_declares_no_opacity():
    """opacity multiplies straight through whatever colour is behind it and
    is invisible to a colour-token contrast check (getComputedStyle().color
    is unaffected by opacity; it is a paint-time effect) -- the previous
    0.6 took an already-compliant --text-muted back down to ~1.8:1. The
    ratio checks above cannot catch a reintroduced opacity, so it needs its
    own guard."""
    block = find_block(STYLE_CSS_TEXT, ".footer-version")
    m = re.search(_PROP_TEMPLATE.format(prop="opacity"), block)
    assert m is None or m.group(1).strip() in ("1", "1.0"), (
        f".footer-version declares opacity: {m.group(1) if m else None!r}, which "
        f"fades --text-muted below 4.5:1 against --bg-secondary in both themes"
    )


# ===========================================================================
# The pairs the admin panel actually renders (admin.css). Admin is dark-only
# (data-theme="dark" data-surface="admin" is static, never toggled), so
# these are checked once, against ADMIN.
# ===========================================================================
ADMIN_PAIRS = [
    (".nav-item.active", ".nav-item.active", "color", ("own",), 4.5),
    (".user-avatar", ".user-avatar", "color", ("own",), 4.5),
    (".user-role", ".user-role", "color", ("parent", ".user-info"), 4.5),
    (".nav-section-title", ".nav-section-title", "color", ("parent", ".sidebar"), 4.5),
    (".stat-card-label", ".stat-card-label", "color", ("parent", ".stat-card"), 4.5),
    ("th", "th", "color", ("own",), 4.5),
    (".status-badge.disabled", ".status-badge.disabled", "color", ("own",), 4.5),
    (".status-badge.active", ".status-badge.active", "color", ("own",), 4.5),
    (".status-badge.syncing", ".status-badge.syncing", "color", ("own",), 4.5),
    (".status-badge.error", ".status-badge.error", "color", ("own",), 4.5),
    (".stat-card-trend.up", ".stat-card-trend.up", "color", ("own",), 4.5),
    (".stat-card-trend.down", ".stat-card-trend.down", "color", ("own",), 4.5),
    (".form-input::placeholder", ".form-input::placeholder", "color", ("parent", ".form-input"), 4.5),
    (".btn-primary", ".btn-primary", "color", ("own",), 4.5),
    (".btn-danger", ".btn-danger", "color", ("own",), 4.5),
    (".modal-close", ".modal-close", "color", ("parent", ".modal"), 4.5),
    (".activity-time", ".activity-time", "color", ("parent", ".card"), 4.5),
    (".login-subtitle", ".login-subtitle", "color", ("parent", ".login-card"), 4.5),
    (".login-error", ".login-error", "color", ("own",), 4.5),
    (".u-text-muted", ".u-text-muted", "color", ("parent", ".card"), 4.5),
    (".log-pre-error", ".log-pre-error", "color", ("parent", ".log-pre"), 4.5),
]


def compute_admin_checks(admin_css_text, admin_theme):
    results = []
    for check_id, fg_selector, fg_prop, bg_source, min_ratio in ADMIN_PAIRS:
        fg_block = find_block(admin_css_text, fg_selector)
        fg_hex = color_hex(admin_theme, declared(fg_block, fg_prop))

        kind = bg_source[0]
        if kind == "own":
            bg_hex = color_hex(admin_theme, declared_background(fg_block))
        elif kind == "parent":
            bg_block = find_block(admin_css_text, bg_source[1])
            bg_hex = color_hex(admin_theme, declared_background(bg_block))
        else:  # pragma: no cover
            raise AssertionError(f"unknown bg_source kind {kind!r}")

        ratio = contrast_ratio(fg_hex, bg_hex)
        results.append((check_id, ratio, min_ratio, fg_hex, bg_hex))
    return results


ADMIN_CSS_TEXT = ADMIN_CSS.read_text(encoding="utf-8")
ADMIN_CHECKS = compute_admin_checks(ADMIN_CSS_TEXT, ADMIN)


@pytest.mark.parametrize(
    "check_id,ratio,min_ratio,fg_hex,bg_hex", ADMIN_CHECKS, ids=[c[0] for c in ADMIN_CHECKS]
)
def test_admin_panel_contrast(check_id, ratio, min_ratio, fg_hex, bg_hex):
    assert ratio >= min_ratio, (
        f"{check_id}: {fg_hex} on {bg_hex} is {ratio:.2f}:1, needs >= {min_ratio}:1"
    )


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
    """The exact pairing this project's notes originally flagged --
    --text-muted's *old* value (slate-400, #8D8DA0) on --bg-tertiary's light
    value (sand-200, #EDE6D9) -- proving the formula correctly identifies a
    real failure when handed one, not just a passing one."""
    old_text_muted_light = "#8D8DA0"
    bg_tertiary_light = resolved_hex(LIGHT, "--bg-tertiary")
    assert contrast_ratio(old_text_muted_light, bg_tertiary_light) < 4.5


def test_text_muted_is_no_longer_the_old_failing_value():
    """Documents that the fix actually changed the token, not just the
    surrounding arithmetic."""
    assert resolved_hex(LIGHT, "--text-muted") != "#8D8DA0"
    assert resolved_hex(DARK, "--text-muted") != "#606078"


def test_white_on_accent_primary_would_fail_in_dark_and_admin():
    """The second originally-flagged pairing: white text is not used on a
    solid --accent-primary fill anywhere any more (see --text-on-accent's
    consumers), but the number itself -- proving why -- must still hold."""
    assert contrast_ratio("#FFFFFF", resolved_hex(DARK, "--accent-primary")) < 4.5
    assert contrast_ratio("#FFFFFF", resolved_hex(ADMIN, "--accent-primary")) < 4.5


# ===========================================================================
# Mutation testing (static half)
#
# Same shape as test_admin_js_escaping.py's MUTATIONS table: (name, old, new,
# must_fail). Each mutation is applied to a copy of the real file text, run
# back through the same builder/checker functions the real suite uses, and
# must turn at least the named check red.
# ===========================================================================
TOKEN_MUTATIONS = [
    (
        "text_muted_light_reverts_to_the_old_failing_shade",
        "--text-muted: var(--c-slate-500);",
        "--text-muted: var(--c-slate-400);",
        ".detail-label [light]",
    ),
    (
        "text_muted_dark_reverts_to_the_old_failing_shade",
        "--text-muted: var(--c-slate-350);",
        "--text-muted: var(--c-slate-500);",
        ".detail-label [dark]",
    ),
    (
        "text_on_accent_reverts_to_white",
        "--text-on-accent: var(--c-navy-900);",
        "--text-on-accent: var(--c-white);",
        None,  # asserted separately: this breaks an ADMIN_CHECKS id, checked below
    ),
    (
        "status_error_text_reverts_to_status_error",
        "--status-error-text: var(--c-red-400);",
        "--status-error-text: var(--c-red-500);",
        None,  # breaks an ADMIN_CHECKS id, checked below
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
    light, dark, admin = build_themes(mutated_text)

    public_results = compute_public_checks(STYLE_CSS_TEXT, {"light": light, "dark": dark})
    admin_results = compute_admin_checks(ADMIN_CSS_TEXT, admin)
    failed_ids = {cid for cid, ratio, min_ratio, *_ in public_results + admin_results if ratio < min_ratio}

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
    rather than "some id or other went red"."""
    mutated_text = TOKENS_TEXT.replace(
        "--text-on-accent: var(--c-navy-900);", "--text-on-accent: var(--c-white);"
    )
    _, _, admin = build_themes(mutated_text)
    results = {cid: ratio for cid, ratio, *_ in compute_admin_checks(ADMIN_CSS_TEXT, admin)}
    assert results[".nav-item.active"] < 4.5
    assert results[".btn-primary"] < 4.5
    assert results[".user-avatar"] < 4.5
    assert results[".btn-danger"] < 4.5


def test_status_error_text_mutation_breaks_the_error_badge():
    mutated_text = TOKENS_TEXT.replace(
        "--status-error-text: var(--c-red-400);", "--status-error-text: var(--c-red-500);"
    )
    _, _, admin = build_themes(mutated_text)
    results = {cid: ratio for cid, ratio, *_ in compute_admin_checks(ADMIN_CSS_TEXT, admin)}
    assert results[".status-badge.error"] < 4.5
    assert results[".log-pre-error"] < 4.5


CSS_MUTATIONS = [
    (
        "nav_link_hover_reverts_to_accent_primary_text",
        STYLE_CSS,
        "STYLE",
        "color: var(--text-primary);\n    background-color: var(--bg-tertiary);",
        "color: var(--accent-primary);\n    background-color: var(--bg-tertiary);",
        ".nav-link:hover [light]",
    ),
    (
        # Background is left alone here: --accent-gradient is not a solid
        # colour, so a checker asked to resolve one as a background is
        # supposed to raise loudly (test_gradient_is_not_a_resolvable_
        # solid_colour below), not silently score it. This isolates the
        # regression this mutation actually means to catch: the text colour.
        "btn_primary_public_reverts_to_white_text",
        STYLE_CSS,
        "STYLE",
        "background: var(--accent-primary);\n    color: var(--text-on-accent);",
        "background: var(--accent-primary);\n    color: white;",
        ".btn-primary [dark]",
    ),
    (
        # A component-file edit, not a token edit: reverts just this one
        # rule's `color` back to --status-error, independent of
        # test_status_error_text_mutation_breaks_the_error_badge below (which
        # mutates the token instead). Both must be caught; a fix at either
        # layer could otherwise mask a regression at the other.
        "status_badge_error_reverts_color_to_status_error",
        ADMIN_CSS,
        "ADMIN",
        ".status-badge.error {\n    background: var(--status-error-bg);\n"
        "    /* status-error-text, not status-error: see tokens.css -- status-error\n"
        "       itself is 3.65-3.71:1 here (needs 4.5:1 as text). */\n"
        "    color: var(--status-error-text);",
        ".status-badge.error {\n    background: var(--status-error-bg);\n"
        "    /* status-error-text, not status-error: see tokens.css -- status-error\n"
        "       itself is 3.65-3.71:1 here (needs 4.5:1 as text). */\n"
        "    color: var(--status-error);",
        ".status-badge.error",
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
        results = compute_admin_checks(mutated, ADMIN)

    failed_ids = {cid for cid, ratio, min_ratio, *_ in results if ratio < min_ratio}
    assert failed_ids, f"mutation {name!r} changed a live rule and nothing failed"
    assert must_fail in failed_ids, (
        f"mutation {name!r} was expected to fail {must_fail!r}, but the "
        f"failures were {sorted(failed_ids)}"
    )


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


_RGB_RE = re.compile(
    r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)"
)


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
    does for the static half, so a translucent .header reads correctly."""
    assert "error" not in measurement, f"harness could not measure this element: {measurement}"
    fg_hex = _rgb_string_to_hex(measurement["color"])
    m = _RGB_RE.fullmatch(measurement["backgroundColor"].strip())
    r, g, b = (round(float(m.group(i))) for i in (1, 2, 3))
    alpha = float(m.group(4)) if m.group(4) is not None else 1.0
    bg_hex = "#%02X%02X%02X" % (r, g, b)
    if alpha < 1.0:
        bg_hex = composite(bg_hex, alpha, page_bg_hex)
    return contrast_ratio(fg_hex, bg_hex)


# (measured_section, key, theme_label_for_page_bg, min_ratio)
DYNAMIC_PUBLIC_CHECKS = [
    ("body", "light", 4.5), ("body", "dark", 4.5),
    (".nav-link", "light", 4.5), (".nav-link", "dark", 4.5),
    (".nav-link:hover", "light", 4.5), (".nav-link:hover", "dark", 4.5),
    (".nav-admin", "light", 4.5), (".nav-admin", "dark", 4.5),
    (".stat-label", "light", 4.5), (".stat-label", "dark", 4.5),
    (".mirror-status", "light", 4.5), (".mirror-status", "dark", 4.5),
    (".detail-label", "light", 4.5), (".detail-label", "dark", 4.5),
    (".btn-primary", "light", 4.5), (".btn-primary", "dark", 4.5),
    (".btn-secondary:hover", "light", 4.5), (".btn-secondary:hover", "dark", 4.5),
    (".footer-content p", "light", 4.5), (".footer-content p", "dark", 4.5),
    (".footer-version", "light", 4.5), (".footer-version", "dark", 4.5),
    (".method-card p", "light", 4.5), (".method-card p", "dark", 4.5),
]


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


DYNAMIC_ADMIN_CHECKS = [
    ".login-subtitle", ".btn-primary", ".nav-item.active", ".user-avatar",
    ".user-role", ".nav-section-title", ".status-badge.disabled",
    ".status-badge.active", "th", ".u-text-muted", ".status-badge.error",
    ".status-badge.syncing", ".form-input::placeholder",
]


@requires_browser
@pytest.mark.parametrize("probe_id", DYNAMIC_ADMIN_CHECKS)
def test_admin_panel_contrast_in_a_real_browser(measured, probe_id):
    page_bg = resolved_hex(ADMIN, "--bg-primary")
    measurement = measured["admin"][probe_id]
    ratio = _measured_ratio(measurement, page_bg)
    assert ratio >= 4.5, (
        f"{probe_id}: real browser measured {measurement}, contrast {ratio:.2f}:1, needs >= 4.5:1"
    )


@requires_browser
def test_dynamic_probe_list_matches_the_harness():
    """The two probe id lists above are a hand-maintained copy of
    PUBLIC_PROBES/ADMIN_PROBES in contrast_harness.mjs. Pins them together the
    same way test_admin_inline_styles.py pins its STYLEHEETS list against
    admin/index.html's actual <link> tags -- so a probe added to one and not
    the other fails loudly here instead of silently measuring nothing."""
    harness_source = HARNESS.read_text(encoding="utf-8")
    public_block = re.search(r"const PUBLIC_PROBES = \[(.*?)\n\];", harness_source, re.S)
    admin_block = re.search(r"const ADMIN_PROBES = \[(.*?)\n\];", harness_source, re.S)
    assert public_block and admin_block

    harness_public_ids = set(re.findall(r"id:\s*'([^']+)'", public_block.group(1)))
    harness_admin_ids = set(re.findall(r"id:\s*'([^']+)'", admin_block.group(1)))

    test_public_ids = {p for p, _, _ in DYNAMIC_PUBLIC_CHECKS}
    test_admin_ids = set(DYNAMIC_ADMIN_CHECKS) | {".form-input::placeholder"}

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
    served to it, not the admin.js path, is what needs mutating."""
    docroot = tmp_path / "public"
    shutil.copytree(REPO_ROOT / "frontend" / "public", docroot)
    admin_css_copy = docroot / "admin" / "css" / "admin.css"

    source = admin_css_copy.read_text(encoding="utf-8")
    old = "background: var(--accent-primary);\n    color: var(--text-on-accent);\n}"
    new = "background: var(--accent-primary);\n    color: white;\n}"
    assert source.count(old) == 1, "admin.css .btn-primary rule no longer matches; update the control"
    admin_css_copy.write_text(source.replace(old, new), encoding="utf-8")

    result = run_contrast_harness(docroot, ADMIN_JS)
    ratio = _measured_ratio(result["admin"][".btn-primary"], resolved_hex(ADMIN, "--bg-primary"))
    assert ratio < 4.5, (
        f"planting color: white back into admin.css's .btn-primary did not make a "
        f"real browser render a failing ratio (measured {ratio:.2f}:1) -- the "
        f"harness is not actually measuring what admin.css renders"
    )
