#!/usr/bin/env python3
"""Print the nginx service's /etc/nginx bind mounts as ``docker run`` arguments.

Why this exists
---------------
The ``nginx`` job in .github/workflows/ci.yml used to hardcode its own ``-v``
flags. That made CI an independent guess at what production looked like, and on
2026-08-31 the guess and production had been different since February:
docker-compose.yml bind-mounted two *individual files* into nginx -- which pins
an inode, so ``git checkout`` (which renames a new file over the old one) never
reached the container -- while the config that actually served the site was an
untracked ``cp default.conf production.conf``. CI validated a layout nothing ran
and reported success, which is the same shape of green-with-nothing-underneath
as the ``nginx -s reload`` that re-read a February file.

So the mount list is no longer written twice. ``docker compose config`` resolves
it once, for the requested NGINX_SITE profile, and this script translates it.
If the mount scheme in docker-compose.yml changes, CI follows automatically; if
it changes in a way this script cannot express, CI fails rather than silently
validating the old layout.

Output is one ``docker run`` argument per line, so the caller can read it into
an array (``mapfile -t args < <(...)``) instead of relying on word splitting.
A bind-mount source containing a space would otherwise be silently split into
two broken arguments.

Usage:  python3 scripts/ci-nginx-mounts.py <profile>      # dev|bootstrap|production
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def fail(message: str) -> "None":
    """Emit a GitHub Actions error annotation and exit non-zero."""
    print(f"::error::{message}", file=sys.stderr)
    raise SystemExit(1)


def compose_nginx_service(profile: str) -> dict:
    env = dict(os.environ, NGINX_SITE=profile)
    proc = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        fail(f"docker compose config failed for NGINX_SITE={profile}: {proc.stderr.strip()[:400]}")
    try:
        doc = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        fail(f"docker compose config did not return JSON: {exc}")
    try:
        return doc["services"]["nginx"]
    except (KeyError, TypeError):
        fail("docker compose config has no services.nginx")
    return {}  # unreachable; keeps type checkers quiet


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        fail("usage: ci-nginx-mounts.py <profile>")
    profile = argv[1]

    service = compose_nginx_service(profile)
    root = os.getcwd()

    volumes = service.get("volumes") or []
    nginx_volumes = [v for v in volumes if str(v.get("target", "")).startswith("/etc/nginx")]

    if not nginx_volumes:
        fail(
            "docker-compose.yml declares no /etc/nginx mounts for the nginx service. "
            "Either the service stopped taking its config from the checkout, or the "
            "mount targets moved and this script no longer recognises them."
        )

    args: list[str] = []
    for vol in nginx_volumes:
        target = vol["target"]
        if vol.get("type") != "bind":
            fail(
                f"the nginx mount at {target} is type={vol.get('type')!r}, not a bind mount. "
                "CI can only reproduce bind mounts; teach this script the new type or "
                "the job would validate something production does not use."
            )
        source = vol.get("source") or ""
        # A mount source outside the checkout cannot be reproduced on a runner,
        # and validating one silently would defeat the point of deriving them.
        if source != root and not source.startswith(root + os.sep):
            fail(f"nginx mount source {source} is outside the checkout ({root})")
        if not os.path.exists(source):
            fail(
                f"nginx mount source {source} (for {target}) does not exist in the checkout. "
                "docker would create it as an empty directory at runtime and nginx would "
                "start with no configuration."
            )
        suffix = ":ro" if vol.get("read_only") else ""
        args += ["-v", f"{source}:{target}{suffix}"]

    # Coverage assertion: every /etc/nginx mount compose declares must appear in
    # the output. This is what makes "CI must change with the scheme" mechanical
    # rather than a note in a review checklist.
    declared = sorted(v["target"] for v in nginx_volumes)
    emitted = sorted(a.rsplit(":", 2)[1] if a.endswith(":ro") else a.split(":")[-1] for a in args[1::2])
    if declared != emitted:
        fail(f"mapped {emitted} but docker-compose.yml declares {declared}")

    print("\n".join(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
