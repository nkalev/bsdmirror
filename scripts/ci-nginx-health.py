#!/usr/bin/env python3
"""Every server block in every nginx site profile must serve /health.

Why this exists
---------------
`location = /health` was defined in the :80 server of
nginx/sites/production/production.conf and nowhere in the :443 server. A
location is matched only inside the server that handled the request, so over
TLS /health fell through to `location /`, hit `try_files ... /index.html`, and
answered 200 with the homepage:

    http://<domain>/health   ->  200  text/plain  OK
    https://<domain>/health  ->  200  text/html   <!DOCTYPE html>...

Every external monitor probes the HTTPS URL. It saw 200 and reported the mirror
healthy. Both of this repo's own probes -- scripts/deploy.sh
verify_security_headers() and the CI header job -- read the status line and the
headers and never the body, so both agreed.

`nginx -t` cannot catch this: the config is perfectly valid. Nor can a
status-code check. This is the structural half of the guard (a definition must
exist in every server block); the CI job that runs alongside it is the
behavioural half (the bytes on the wire, per profile, per scheme).

Usage:  python3 scripts/ci-nginx-health.py [site-dir]        # default: nginx/sites
Exit:   0 clean, 1 a server block is missing the include
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REQUIRED_INCLUDE = "include /etc/nginx/host/snippets/health.conf;"

# The snippet's own path, relative to the repo root. Its container path is
# /etc/nginx/host/snippets/... because docker-compose.yml mounts ./nginx there.
SNIPPET = Path("nginx/snippets/health.conf")


def strip_comments(text: str) -> str:
    """Remove `#` comments without cutting a `#` that sits inside a string."""
    out = []
    for line in text.splitlines():
        quote = ""
        cut = len(line)
        for i, ch in enumerate(line):
            if quote:
                if ch == quote:
                    quote = ""
            elif ch in "\"'":
                quote = ch
            elif ch == "#":
                cut = i
                break
        out.append(line[:cut])
    return "\n".join(out)


def server_blocks(text: str):
    """Yield (line_number, body) for each top-level `server { ... }` block."""
    depth = 0
    start = None
    start_line = 0
    line_of = [0] * (len(text) + 1)
    line = 1
    for i, ch in enumerate(text):
        line_of[i] = line
        if ch == "\n":
            line += 1
    line_of[len(text)] = line

    for match in re.finditer(r"[{}]", text):
        i = match.start()
        if text[i] == "{":
            if depth == 0:
                # Walk back over whitespace to the directive that opened it.
                head = text[:i].rstrip()
                if re.search(r"(^|\n)\s*server$", head):
                    start = i + 1
                    start_line = line_of[i]
            depth += 1
        else:
            depth -= 1
            if depth == 0 and start is not None:
                yield start_line, text[start:i]
                start = None
    if depth != 0:
        raise SystemExit(f"::error::unbalanced braces while parsing (depth {depth})")


def main(argv: list[str]) -> int:
    sites = Path(argv[1]) if len(argv) > 1 else Path("nginx/sites")

    problems: list[str] = []

    if not SNIPPET.is_file():
        problems.append(
            f"{SNIPPET} is missing. Every site profile includes it; without the file "
            "nginx refuses to start, so this is a hard stop rather than a lint."
        )

    confs = sorted(sites.glob("*/*.conf"))
    if not confs:
        problems.append(f"no site configs found under {sites}/*/*.conf -- the layout moved")

    total_servers = 0
    for conf in confs:
        body = strip_comments(conf.read_text())
        blocks = list(server_blocks(body))
        if not blocks:
            problems.append(f"{conf}: contains no server block")
            continue
        for line_no, block in blocks:
            total_servers += 1
            listens = " ".join(sorted(set(re.findall(r"\blisten\s+([^\s;]+)", block)))) or "?"
            if REQUIRED_INCLUDE in block:
                print(f"ok   {conf}:{line_no}  server (listen {listens})  includes health.conf")
            else:
                problems.append(
                    f"{conf}:{line_no}: server block (listen {listens}) does not "
                    f"'{REQUIRED_INCLUDE}'. /health would fall through to whatever "
                    "location matches next -- for a block with an index/try_files "
                    "fallback that is a 200 with the homepage, which every monitor "
                    "reads as healthy."
                )

    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        return 1

    print(f"\n{total_servers} server block(s) across {len(confs)} site profile(s) all serve /health")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
