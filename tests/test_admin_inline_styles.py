"""The admin panel's markup must carry no inline style attributes, and every
class it names must actually exist.

Two separate failures are guarded here, and they fail in opposite directions.

An inline `style="..."` is why the CSP still needs `style-src 'unsafe-inline'`.
One attribute anywhere in the rendered markup is enough to keep that directive,
and the directive is what makes a style-context injection exploitable, so the
count has to be zero rather than small. It was 24 before this suite existed.

A class that is named in the markup but defined in no stylesheet renders as
nothing at all -- no error, no warning, just an element with the wrong layout.
That is the specific risk of moving declarations out of inline attributes: the
inline version could not be misspelled into oblivion, and a class can.
"""

import pathlib
import re

from tests.test_admin_js_escaping import strip_js_comments

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ADMIN_JS = REPO_ROOT / "frontend" / "public" / "admin" / "js" / "admin.js"
ADMIN_INDEX = REPO_ROOT / "frontend" / "public" / "admin" / "index.html"

# Exactly the stylesheets admin/index.html <link>s, and deliberately NOT
# frontend/public/css/style.css: the admin page does not load it. Counting it
# as a definition source would let a class defined only there pass this check
# and still render unstyled in the panel -- the check failing open in the one
# direction it exists to catch.
STYLESHEETS = [
    REPO_ROOT / "frontend" / "public" / "css" / "fonts.css",
    REPO_ROOT / "frontend" / "public" / "css" / "tokens.css",
    REPO_ROOT / "frontend" / "public" / "admin" / "css" / "admin.css",
]


def _strip_interpolations(value: str) -> str:
    """Remove ${...} spans from a class attribute.

    admin.js builds markup with a tagged template, so a class attribute often
    reads `class="tab ${active ? 'active' : ''}"`. Splitting that on whitespace
    without stripping first yields `${active`, `?`, `'active'` and `:` as class
    names -- a check that reports nine missing classes on a healthy tree, which
    is a check nobody will keep. Nested braces are handled by counting depth.
    """
    out, depth, i = [], 0, 0
    while i < len(value):
        if value.startswith("${", i):
            depth += 1
            i += 2
            continue
        if depth and value[i] == "}":
            depth -= 1
            i += 1
            continue
        if not depth:
            out.append(value[i])
        i += 1
    return "".join(out)


def _static_classes_used() -> set:
    js = ADMIN_JS.read_text()
    used = set()
    for attr in re.findall(r'class="([^"]*)"', js):
        for token in _strip_interpolations(attr).split():
            if re.fullmatch(r"[a-zA-Z][\w-]*", token):
                used.add(token)
    return used


def _classes_in(css: str) -> set:
    # A selector quoted in a comment is not a rule: delete the rule and leave
    # the comment, and the class would still read as defined.
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    # A class only counts as defined where it terminates a selector: `.foo{`,
    # `.foo,`, `.foo.bar`, `.foo::before`, `.foo > x`. Matching `\.([\w-]+)`
    # anywhere would also pick up decimals inside declarations such as
    # `flex: 1.5` and quietly define classes named after them.
    return set(re.findall(r"\.([a-zA-Z][\w-]*)(?=[\s,{:.>+~\[])", css))


def _classes_defined() -> set:
    return _classes_in("\n".join(p.read_text() for p in STYLESHEETS))


def test_admin_markup_has_no_inline_style_attributes():
    js = ADMIN_JS.read_text()
    offenders = re.findall(r'style="[^"]*"', js)
    assert offenders == [], (
        "%d inline style attribute(s) in admin.js. Each one is a reason the CSP "
        "must keep style-src 'unsafe-inline'. Move the declarations into "
        "frontend/public/admin/css/admin.css and name a class instead:\n  %s"
        % (len(offenders), "\n  ".join(offenders[:10]))
    )


def test_every_class_in_admin_markup_is_defined_somewhere():
    missing = sorted(_static_classes_used() - _classes_defined())
    assert not missing, (
        "admin.js names these classes and no stylesheet defines them, so the "
        "elements render unstyled with no error anywhere: %s" % missing
    )


def test_the_check_can_actually_find_a_missing_class():
    """A guard that cannot fail is not a guard.

    test_every_class_in_admin_markup_is_defined_somewhere passes on a healthy
    tree, which on its own is also what a broken extractor looks like. This
    pins that a name absent from every stylesheet is genuinely reported.
    """
    assert "definitely-not-a-real-class" not in _classes_defined()


# ---------------------------------------------------------------------------
# Icon classes that never sit in a class="..." attribute of their own.
#
# _static_classes_used() reads class="..." attributes and strips every ${...}
# out of them, so a class that reaches the page through a ternary arm or a
# lookup-table value is invisible to it. Eight icon classes come that way:
# icon-sun and icon-moon (renderThemeToggle() and updateThemeToggles()),
# icon-info (Toast.show()), and icon-unlock, icon-lock, icon-user, icon-edit
# and icon-trash (getActivityIcon()). Spec 4.7 has admin.js write every icon
# class in full, as plain text, so a text search finds them -- and until this
# one existed, deleting `.icon-sun` from admin.css passed every test.
# ---------------------------------------------------------------------------
INDIRECT_ICONS = {
    "icon-sun",
    "icon-moon",
    "icon-info",
    "icon-unlock",
    "icon-lock",
    "icon-user",
    "icon-edit",
    "icon-trash",
}
ICON_NAME = re.compile(r"(?<![\w-])icon-[a-z-]+")
# `icon-` with no letter after it: the start of a name built at runtime
# (`icon-${name}`, 'icon-' + name), which no text search can see through.
ICON_NAME_ASSEMBLED = re.compile(r"(?<![\w-])icon-(?![a-z])")


def _admin_code() -> str:
    """admin.js with its comments blanked: a name in a comment renders nothing."""
    return strip_js_comments(ADMIN_JS.read_text())


def _icon_classes_named() -> set:
    return set(ICON_NAME.findall(_admin_code()))


def test_every_icon_class_admin_js_names_has_a_rule():
    missing = sorted(_icon_classes_named() - _classes_defined())
    assert not missing, (
        "admin.js names these icon classes and no stylesheet admin/index.html links has a rule "
        "for them, so the icon renders as nothing with no error anywhere: %s" % missing
    )


def test_the_icon_scan_sees_the_names_the_attribute_scan_cannot():
    """The check above passes on a healthy tree, which is also what a scan that
    sees nothing looks like. These eight are the names the class-attribute scan
    never reaches; if admin.js stops writing one in full, this says so instead
    of the guard going quietly blind."""
    missing = sorted(INDIRECT_ICONS - _icon_classes_named())
    assert not missing, (
        "the icon scan no longer finds %s in admin.js. Spec 4.7: write every icon class in "
        "full, as literal text." % missing
    )


def test_no_icon_class_is_assembled_at_runtime():
    assembled = [m.start() for m in ICON_NAME_ASSEMBLED.finditer(_admin_code())]
    assert not assembled, (
        "admin.js builds an icon class at runtime (icon- followed by something other than a "
        "letter). Spec 4.7: write the full class, never `icon-${name}`; the scan above cannot "
        "check a name that does not exist as text."
    )


def test_the_icon_rule_check_can_actually_find_a_missing_rule():
    """A rule that is gone, or that only survives inside a comment, must read as missing."""
    css = "/* .icon-sun { mask-image: url(/img/icons/sun.svg); } */\n.icon-moon {\n}\n"
    defined = _classes_in(css)
    assert "icon-moon" in defined
    assert "icon-sun" not in defined


def test_the_utilities_added_for_this_change_are_all_referenced():
    """Dead utility CSS is how a token system starts drifting from the markup.

    Every class listed here was introduced to replace a specific inline style;
    if one stops being used, either the markup regressed or the rule should go.
    """
    introduced = {
        "u-mt-sm",
        "u-mt-md",
        "u-push-right",
        "u-pad-body",
        "u-full-width",
        "u-flex-1",
        "u-text-muted",
        "u-text-error",
        "u-text-sm",
        "u-row-8",
        "u-row-12",
        "u-grid-2",
        "u-grid-2-tight",
        "code-block",
        "log-pre",
        "log-pre-error",
        "log-pre-output",
    }
    unused = sorted(introduced - _static_classes_used())
    assert not unused, "defined but never used in admin.js markup: %s" % unused


def test_the_stylesheet_list_matches_what_the_admin_page_loads():
    """STYLESHEETS above is a hand-maintained copy of admin/index.html's <link>
    tags. If someone adds a stylesheet to the page and not to this list, the
    class check silently stops seeing those definitions and starts reporting
    false failures; drop one from the page and it starts passing on classes
    that no longer resolve. Pin the two together."""
    html = ADMIN_INDEX.read_text()
    linked = re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', html)
    linked_names = {pathlib.PurePosixPath(h).name for h in linked}
    listed_names = {p.name for p in STYLESHEETS}
    assert linked_names == listed_names, "admin/index.html links %s but this module checks %s" % (
        sorted(linked_names),
        sorted(listed_names),
    )
