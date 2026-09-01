"""Is the built image the same code as the checkout it is being run from?

    python /app/alembic/fingerprint.py /app /checkout

Prints a digest for each root and exits 1 if they differ.

WHY THIS EXISTS
---------------
scripts/migrate.sh runs alembic INSIDE the backend image, because that is where
alembic, the migration scripts and shared/models/ all live and it is the only
place on the `backend` compose network -- which is `internal: true` -- that can
reach postgres.

That means every answer it gives is an answer about the IMAGE. If the image was
built before the model change you are trying to generate a migration for,
`alembic revision --autogenerate` compares the OLD models against the database,
finds nothing, and writes a migration whose upgrade() is `pass`. It succeeds.
It says "done". It is wrong, and nothing in the output suggests it.

That happened while this file was being written, which is why it exists.

WHAT IS HASHED, AND WHY ONLY THIS
---------------------------------
Exactly the two trees that decide what a migration contains:

    shared/models/**.py     the metadata autogenerate compares against
    alembic/**.py           env.py, the comparison options, and versions/

Not backend/app/**: a change to a route does not change a schema, and hashing it
would make this warn on every unrelated rebuild until people stopped reading it.

Content only -- not mtime, not inode, not file mode. Two checkouts of the same
commit fingerprint identically, which is what makes this usable on a server
where the working tree is written by `git checkout`.
"""
import hashlib
import sys
from pathlib import Path

# Relative to each root. In the image: /app/shared, /app/alembic. With the
# checkout mounted so that the same two names appear under /checkout, the
# layouts line up and the digests are directly comparable.
SUBTREES = ("shared/models", "alembic")


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    seen = 0
    for subtree in SUBTREES:
        base = root / subtree
        if not base.is_dir():
            digest.update(b"MISSING:" + subtree.encode() + b"\n")
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            digest.update(str(path.relative_to(root)).encode() + b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
            seen += 1
    if seen == 0:
        # A digest over nothing is a digest that matches any other digest over
        # nothing, which would make two broken roots look consistent.
        raise SystemExit("fingerprint: no .py files under %s/{%s}" % (root, ",".join(SUBTREES)))
    return digest.hexdigest()[:16]


def main(argv) -> int:
    if len(argv) != 3:
        print(__doc__.splitlines()[2].strip(), file=sys.stderr)
        return 2
    a, b = Path(argv[1]), Path(argv[2])
    fa, fb = fingerprint(a), fingerprint(b)
    print("%s  %s" % (fa, a))
    print("%s  %s" % (fb, b))
    return 0 if fa == fb else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
