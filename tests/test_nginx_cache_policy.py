"""Which cache policy and which rate limit each kind of file gets in production.

docs/design/2026-09-25-reflection-redesign.md, section 8. The redesign ships
new HTML, CSS and JS across several pull requests under the same unversioned
filenames. Under the old `expires 7d` plus `immutable`, a returning visitor
would pair new HTML with week-old CSS. So, in the :443 server:

* pages, stylesheets and scripts revalidate on every load (`expires epoch`,
  which nginx sends as `Cache-Control: no-cache`; an unchanged file costs a
  304);
* fonts and images keep `expires 7d` and `public, immutable`, because they
  change only under a new filename;
* the admin console's CSS and JS move from api_limit (burst 10, shared with
  /api/) to general_limit (burst 30). Revalidating them on every load would
  otherwise stack them on top of the dashboard's own API calls.

These tests do not grep for directive strings. They parse
nginx/sites/production/production.conf, resolve each URI to the location nginx
would pick, in nginx's own order, and read the directives that location ends up
with after inheritance. A regex location added in the wrong place, or an
extension moved into the wrong block, changes the answer here the way it would
change it in production.

What this cannot prove is that nginx runs this file. scripts/deploy.sh's
verify_cache_headers() reads the live headers after every deploy.
"""

import pathlib
import re
from dataclasses import dataclass, field

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PRODUCTION_CONF = REPO_ROOT / "nginx" / "sites" / "production" / "production.conf"
SNIPPET = "/etc/nginx/host/snippets/security-headers-tls.conf"

TOKEN = re.compile(
    r"""
      (?P<comment>\#[^\n]*)
    | (?P<quoted>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
    | (?P<punct>[{};])
    | (?P<word>[^\s{};"'\#]+)
    """,
    re.X,
)


@dataclass
class Block:
    """A `name args { ... }` block: the file itself, a server or a location."""

    name: str
    args: list[str]
    parent: "Block | None" = None
    directives: list[list[str]] = field(default_factory=list)
    children: list["Block"] = field(default_factory=list)


def parse(text: str) -> Block:
    """Just enough of nginx's grammar for this file: words, quoted strings, `;`,
    `{}` and comments. `include`d files are not expanded. The snippets add only
    headers and the /health location, which no URI below reaches."""
    root = Block("file", [])
    stack = [root]
    words: list[str] = []
    for match in TOKEN.finditer(text):
        kind, token = match.lastgroup, match.group()
        if kind == "comment":
            continue
        if kind == "quoted":
            words.append(token[1:-1])
        elif kind == "word":
            words.append(token)
        elif token == ";":
            stack[-1].directives.append(words)
            words = []
        elif token == "{":
            block = Block(words[0], words[1:], parent=stack[-1])
            stack[-1].children.append(block)
            stack.append(block)
            words = []
        else:
            assert not words, f"unterminated directive before '}}': {words}"
            stack.pop()
    assert len(stack) == 1 and not words, "unbalanced braces"
    return root


def locations(block: Block) -> list[Block]:
    return [child for child in block.children if child.name == "location"]


def modifier(location: Block) -> str:
    return location.args[0] if len(location.args) == 2 else ""


def pattern(location: Block) -> str:
    return location.args[-1]


def label(location: Block) -> str:
    return "location " + " ".join(location.args)


def find_location(level: Block, uri: str) -> tuple[Block | None, bool]:
    """nginx's ngx_http_core_find_location(), for the syntax this file uses.

    An exact (`=`) match wins outright. Otherwise the longest plain prefix is
    remembered and its nested locations are searched; an exact or regex match
    there ends the search. Then this level's regexes, in file order, and the
    first match ends the search. Failing all of that, the remembered prefix.
    The flag in the result says whether the search ended (exact or regex) or
    only fell back to a prefix, which the caller's own regexes may override.
    """
    candidates = locations(level)
    for location in candidates:
        if modifier(location) not in ("", "=", "~", "~*"):
            raise NotImplementedError(f"{label(location)}: extend find_location() first")
    for location in candidates:
        if modifier(location) == "=" and pattern(location) == uri:
            return location, True
    prefixes = [
        location
        for location in candidates
        if modifier(location) == "" and uri.startswith(pattern(location))
    ]
    chosen = max(prefixes, key=lambda location: len(pattern(location)), default=None)
    if chosen is not None and locations(chosen):
        nested, final = find_location(chosen, uri)
        if final:
            return nested, True
        chosen = nested or chosen
    for location in candidates:
        flags = {"~": 0, "~*": re.IGNORECASE}.get(modifier(location))
        if flags is not None and re.search(pattern(location), uri, flags):
            nested = find_location(location, uri)[0] if locations(location) else None
            return nested or location, True
    return chosen, False


def own(location: Block, name: str) -> list[list[str]]:
    """The `name` directives set in this block itself. try_files is read this
    way, because a nested location does not inherit it."""
    return [directive for directive in location.directives if directive[0] == name]


def inherited(location: Block, name: str) -> list[list[str]]:
    """The `name` directives in force at a location: its own if it has any,
    otherwise its parent's, and so on up to the server. expires, limit_req and
    root inherit this way (nginx keeps root and alias as one setting)."""
    level = location
    while level is not None:
        found = own(level, name)
        if found:
            return found
        level = level.parent
    return []


def inherited_headers(location: Block) -> list[list[str]]:
    """The add_header set in force: that of the nearest level defining any
    header, counting an include of either security-header snippet as defining
    them all -- the TLS one carries HSTS, the plain one does not. One
    add_header at a level drops every inherited one; that is the trap
    nginx/snippets/ exists for."""
    level = location
    while level is not None:
        found = [
            directive
            for directive in level.directives
            if directive[0] == "add_header"
            or (directive[0] == "include" and "/snippets/security-headers" in directive[1])
        ]
        if found:
            return found
        level = level.parent
    return []


@pytest.fixture(scope="module")
def tls_server() -> Block:
    conf = parse(PRODUCTION_CONF.read_text(encoding="utf-8"))
    servers = [block for block in conf.children if block.name == "server"]
    tls = [server for server in servers if ["listen", "443", "ssl"] in server.directives]
    assert len(tls) == 1, "expected exactly one `listen 443 ssl` server"
    return tls[0]


def resolve(server: Block, uri: str) -> Block:
    location, _ = find_location(server, uri)
    assert location is not None, f"no location matches {uri}"
    return location


REVALIDATED = [
    "/",
    "/index.html",
    "/404.html",
    "/css/style.css",
    "/css/tokens.css",
    "/css/fonts.css",
    "/js/main.js",
    "/js/theme-init.js",
    "/admin/",
    "/admin/index.html",
    "/admin/css/admin.css",
    "/admin/js/admin.js",
]
LONG_CACHED = [
    "/fonts/jetbrains-mono-latin.woff2",
    "/img/favicon.svg",
    "/img/freebsd-logo.svg",
    "/img/icons/copy.svg",
    "/img/apple-touch-icon.png",
    "/favicon.ico",
]
ADMIN_ASSETS = ["/admin/css/admin.css", "/admin/js/admin.js"]

# The location nginx must pick for each URI. This pins find_location() to
# nginx's order as much as it pins the file.
SELECTION = [
    ("/api/auth/token", "location = /api/auth/token"),
    ("/api/health", "location /api/"),
    ("/admin/", "location /admin"),
    ("/admin/js/admin.js", "location ~ ^/admin/(css|js)/"),
    ("/admin/css/admin.css", "location ~ ^/admin/(css|js)/"),
    ("/index.html", "location /"),
    ("/css/style.css", r"location ~* \.(css|js)$"),
    ("/js/main.js", r"location ~* \.(css|js)$"),
    ("/img/favicon.svg", r"location ~* \.(png|jpg|jpeg|gif|ico|svg|woff|woff2)$"),
    ("/FreeBSD/README.TXT", "location /FreeBSD/"),
    # The nested blocks live in `location /`, so they never reach the mirror
    # trees.
    ("/FreeBSD/logo.svg", "location /FreeBSD/"),
    ("/FreeBSD/doc/style.css", "location /FreeBSD/"),
    ("/NetBSD/x.js", "location /NetBSD/"),
    ("/OpenBSD/x.css", "location /OpenBSD/"),
    ("/50x.html", "location = /50x.html"),
]


@pytest.mark.parametrize("uri, expected", SELECTION)
def test_each_uri_reaches_the_location_the_design_expects(tls_server, uri, expected):
    assert label(resolve(tls_server, uri)) == expected


@pytest.mark.parametrize("uri", REVALIDATED)
def test_pages_styles_and_scripts_revalidate_on_every_load(tls_server, uri):
    location = resolve(tls_server, uri)
    message = f"{uri} is served by `{label(location)}` without `expires epoch`"
    assert inherited(location, "expires") == [["expires", "epoch"]], message
    # expires epoch already sends Cache-Control: no-cache. An add_header
    # Cache-Control on top would send a second, contradicting value.
    cache_headers = [
        directive
        for directive in inherited_headers(location)
        if directive[:2] == ["add_header", "Cache-Control"]
    ]
    assert not cache_headers, f"{uri} would get two Cache-Control headers"


@pytest.mark.parametrize("uri", LONG_CACHED)
def test_fonts_and_images_stay_cached_for_a_week(tls_server, uri):
    location = resolve(tls_server, uri)
    assert inherited(location, "expires") == [["expires", "7d"]]
    assert ["add_header", "Cache-Control", "public, immutable"] in inherited_headers(location)


@pytest.mark.parametrize(
    "uri",
    ["/api/health", "/FreeBSD/README.TXT", "/NetBSD/README", "/OpenBSD/README", "/50x.html"],
)
def test_the_api_the_mirror_trees_and_the_error_page_set_no_expires(tls_server, uri):
    # expires belongs to the static-file blocks. Moved up to the server, it
    # would put no-cache on every mirror download and on the backend's replies.
    assert inherited(resolve(tls_server, uri), "expires") == []


@pytest.mark.parametrize("uri", [*REVALIDATED, *LONG_CACHED])
def test_every_static_response_keeps_the_security_headers(tls_server, uri):
    assert ["include", SNIPPET] in inherited_headers(resolve(tls_server, uri))


@pytest.mark.parametrize("uri", ADMIN_ASSETS)
def test_admin_css_and_js_share_the_static_file_limit(tls_server, uri):
    assert inherited(resolve(tls_server, uri), "limit_req") == [
        ["limit_req", "zone=general_limit", "burst=30", "nodelay"]
    ]


@pytest.mark.parametrize("uri", ["/admin/", "/admin/index.html"])
def test_the_admin_page_itself_stays_on_the_api_limit(tls_server, uri):
    assert inherited(resolve(tls_server, uri), "limit_req") == [
        ["limit_req", "zone=api_limit", "burst=10", "nodelay"]
    ]


@pytest.mark.parametrize("uri", ["/admin/", *ADMIN_ASSETS])
def test_the_admin_console_keeps_its_noindex_header(tls_server, uri):
    noindex = ["add_header", "X-Robots-Tag", "noindex, nofollow", "always"]
    assert noindex in inherited_headers(resolve(tls_server, uri))


@pytest.mark.parametrize("uri", ADMIN_ASSETS)
def test_admin_assets_are_read_from_the_files_the_alias_maps(tls_server, uri):
    # /admin uses `alias /var/www/public/admin`. The asset block serves from
    # the server root instead, which maps /admin/js/admin.js to the same file.
    location = resolve(tls_server, uri)
    assert inherited(location, "alias") == []
    assert inherited(location, "root") == [["root", "/var/www/public"]]


@pytest.mark.parametrize("uri", ["/css/style.css", "/js/main.js", *ADMIN_ASSETS])
def test_a_missing_stylesheet_or_script_is_a_404_not_a_page(tls_server, uri):
    # Each block that serves CSS or JS sets its own try_files, so a missing
    # file is a 404 rather than index.html served in its place, whatever the
    # block would otherwise inherit.
    assert own(resolve(tls_server, uri), "try_files") == [["try_files", "$uri", "=404"]]
