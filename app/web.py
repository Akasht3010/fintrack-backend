"""Serve the Expo web export (built into ./web) from the same service as the API.

The whole app runs as one Cloud Run service: FastAPI handles /api/*, /health,
/docs, and everything else falls through to the static web build. When ./web
isn't present (local dev, tests, an API-only image) this is a no-op.
"""
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
INDEX = os.path.join(WEB_DIR, "index.html")

# Paths the API owns — the catch-all must not answer these with index.html.
_API_PREFIXES = ("api/", "docs", "redoc", "openapi.json", "health")


def mount_web(app: FastAPI) -> None:
    if not os.path.isfile(INDEX):
        return

    # Hashed, immutable build output — safe to let StaticFiles serve directly.
    for sub in ("_expo", "assets"):
        d = os.path.join(WEB_DIR, sub)
        if os.path.isdir(d):
            app.mount(f"/{sub}", StaticFiles(directory=d), name=sub)

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith(_API_PREFIXES):
            return Response(status_code=404)

        # Mirrors Expo's recommended nginx `try_files $uri $uri.html /index.html`.
        if path:
            safe = os.path.normpath(path)
            if not safe.startswith(".."):
                for candidate in (
                    os.path.join(WEB_DIR, safe),
                    os.path.join(WEB_DIR, safe + ".html"),
                    os.path.join(WEB_DIR, safe, "index.html"),
                ):
                    if os.path.isfile(candidate):
                        return FileResponse(candidate)

        return FileResponse(INDEX)
