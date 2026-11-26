from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from stockbot.web.auth import Auth
from stockbot.web.routes import build_router


def create_app(deps, settings, static_dir: Path | None = None,
               now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> FastAPI:
    app = FastAPI(title="JsonParc Stock Bot", docs_url=None, redoc_url=None, openapi_url=None)
    auth = Auth(settings.secret_key, settings.web_password)
    app.include_router(build_router(deps, settings, auth, now_fn))

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    if static_dir is not None and Path(static_dir).exists():
        root = Path(static_dir).resolve()

        @app.get("/{path:path}")
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "not found"}, status_code=404)
            target = (root / path).resolve()
            if path and target.is_file() and root in target.parents:
                return FileResponse(target)
            return FileResponse(root / "index.html")

    return app
