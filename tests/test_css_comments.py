"""CSS comment hygiene, across every hand-written stylesheet.

A `/* ... */` comment ends at its *first* `*/`, wherever that falls. A header
comment that lists several token globs separated by `/` -- `--bg-*/--text-*`
-- plants a `*/` of its own in the middle of the sentence, which closes the
comment right there. Everything from that point to the next `*/` a browser
happens to find is no longer a comment at all: it is parsed as CSS, fails to
parse as any rule the language defines, and is dropped -- taking whatever
real rule used to sit just after the intended close with it. That is what
admin.css's header comment did in PR 3: it listed `--bg-*/--text-*`, and the
rule under its "Reset" banner went with it.

Every `*/` in these four stylesheets must therefore be followed by
whitespace or nothing (the end of the file), and no comment may contain a
`*/` before the one that actually ends it.
"""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STYLE_CSS = REPO_ROOT / "frontend" / "public" / "css" / "style.css"
ERROR_CSS = REPO_ROOT / "frontend" / "public" / "css" / "error.css"
TOKENS_CSS = REPO_ROOT / "frontend" / "public" / "css" / "tokens.css"
ADMIN_CSS = REPO_ROOT / "frontend" / "public" / "admin" / "css" / "admin.css"
STYLESHEETS = [STYLE_CSS, ERROR_CSS, TOKENS_CSS, ADMIN_CSS]

COMMENT_CLOSE_RE = re.compile(r"\*/")
COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def comment_closers_not_followed_by_whitespace(css_text):
    """Every `*/` in the text, checked on its own: the character right
    after it must be whitespace, or there must be no character at all (end
    of file). A `*/` glued to whatever comes next -- admin.css's
    `--bg-*/--text-*` shape -- means some earlier, unintended `*/` inside
    what was meant to be one long comment closed it early. Returns a list
    of (line_number, context) pairs, one per offending closer."""
    offenders = []
    for m in COMMENT_CLOSE_RE.finditer(css_text):
        end = m.end()
        following = css_text[end : end + 1]
        if following and not following.isspace():
            line_no = css_text.count("\n", 0, m.start()) + 1
            context = css_text[max(0, m.start() - 24) : end + 12]
            offenders.append((line_no, context))
    return offenders


def stray_closers_after_stripping_well_formed_comments(css_text):
    """The same property, checked from the other direction: remove every
    well-formed `/* ... */` span (non-greedy, so each removal stops at the
    first closer it meets, exactly like a real CSS parser) and see whether
    a `*/` is left over as plain text. One survives only when some comment
    closed earlier than its author intended, stranding a later, real `*/`
    outside any comment at all. Returns the stray closers' offsets into the
    stripped text."""
    stripped = COMMENT_RE.sub("", css_text)
    return [m.start() for m in COMMENT_CLOSE_RE.finditer(stripped)]


def test_every_comment_closer_is_followed_by_whitespace_or_end_of_file():
    offenders = []
    for sheet in STYLESHEETS:
        text = sheet.read_text(encoding="utf-8")
        for line_no, context in comment_closers_not_followed_by_whitespace(text):
            offenders.append(f"{sheet.name}:{line_no}: {context!r}")
    assert offenders == [], (
        "a `*/` is glued directly to whatever follows it, which means some "
        "earlier comment closed before its author meant it to:\n  " + "\n  ".join(offenders)
    )


def test_no_closer_survives_stripping_every_well_formed_comment():
    offenders = [
        sheet.name
        for sheet in STYLESHEETS
        if stray_closers_after_stripping_well_formed_comments(sheet.read_text(encoding="utf-8"))
    ]
    assert offenders == [], (
        "a `*/` remains after every /* ... */ span is stripped out, which means "
        "one comment closed early and left a later `*/` stranded as plain text: "
        + ", ".join(offenders)
    )


def test_the_checks_actually_catch_a_planted_defect():
    """Both checks above first ran against admin.css's header comment, the one
    that closed early (see the module docstring); plant that shape in
    miniature -- a `*/` glued to the text after it, `*/x` -- and confirm both
    formulations catch it, and that neither fires on an ordinary, well-formed
    comment."""
    planted = "/* token list --a-*/x more words, closed for real */\n.y { color: red; }\n"
    assert comment_closers_not_followed_by_whitespace(
        planted
    ), "the whitespace check let a `*/` glued to following text through"
    assert stray_closers_after_stripping_well_formed_comments(
        planted
    ), "the strip-based check let a `*/` glued to following text through"

    well_formed = "/* a normal, single comment */\n.y { color: red; }\n"
    assert not comment_closers_not_followed_by_whitespace(well_formed)
    assert not stray_closers_after_stripping_well_formed_comments(well_formed)


def test_the_checks_cover_style_css_error_css_tokens_css_and_admin_css():
    """The checks above loop over STYLESHEETS; this pins that list to all
    four files, so a typo in it cannot silently shrink every check to fewer."""
    assert {p.name for p in STYLESHEETS} == {"style.css", "error.css", "tokens.css", "admin.css"}
