"""Serve the built Svelte shell after normal HTTP routes have been resolved."""

import re
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, FastAPI
from starlette.types import Receive, Scope, Send

FRONTEND_BUILD = Path(__file__).resolve().parents[3] / "frontend" / "build"
FRONTEND_REBUILD = "Run pnpm --dir frontend build from the repository root."
BUILT_LINK = re.compile(r"""(?:href|src)=["'](/_app/immutable/[^"']+)["']""")


def frontend_available(build: Path) -> bool:
    try:
        links = BUILT_LINK.findall((build / "index.html").read_text(encoding="utf-8"))
        assets = [build / link.removeprefix("/") for link in links]
        return {".js", ".css"} <= {asset.suffix for asset in assets} and all(
            asset.is_file() for asset in assets
        )
    except OSError, UnicodeError:
        return False


def install_frontend(app: FastAPI, build: Path) -> None:
    if not frontend_available(build):
        raise RuntimeError(f"Frontend build missing or incomplete. {FRONTEND_REBUILD}")

    frontend = APIRouter()
    frontend.frontend("/", directory=build, fallback="index.html", check_dir=True)
    api_not_found = app.router.default

    async def fallback(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await api_not_found(scope, receive, send)
            return
        parts = PurePosixPath(scope["path"]).parts[1:]
        if parts and parts[0] in {"api", "health"}:
            # Preserve native route matching, slash redirects, method errors and JSON 404s.
            await api_not_found(scope, receive, send)
            return
        if parts and (parts[0] == "_app" or any("." in part for part in parts)):
            # FastAPI normally falls back for HTML requests. File URLs must
            # still return 404 on a miss when entered in the address bar.
            scope = {
                **scope,
                "headers": [
                    (key, value) for key, value in scope["headers"] if key != b"accept"
                ],
            }
        await frontend(scope, receive, send)

    app.router.default = fallback
