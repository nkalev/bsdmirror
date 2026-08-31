"""Code shared by the backend API and the sync service.

Both services run from source inside their own container -- neither is
pip-installed -- so this package is made importable by being *at the root of
each image's WORKDIR*:

    backend image   COPY backend/ .        -> /app/app/...     WORKDIR /app
                    COPY shared/ ./shared  -> /app/shared/...
    sync image      COPY sync/ .           -> /app/sync_service.py
                    COPY shared/ ./shared  -> /app/shared/...

/app is on sys.path in both (uvicorn inserts its --app-dir, which defaults to
".", and `python -m` inserts the cwd), so `import shared.models` resolves the
same way in both images and in a bare checkout, where pyproject.toml's
`pythonpath = ["backend", "."]` already puts the repo root on the path.

Nothing here may import from `app.*` or from `sync_service`. The dependency
runs one way only: services depend on shared, never the reverse. That is what
lets the sync service import these models without dragging in FastAPI.
"""
