"""FastAPI application factory for Moulaga."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .routers import (
    accounts,
    budget,
    budgets,
    categories,
    household,
    merchants,
    preferences,
    recurring,
    rules,
    transactions,
    wealth,
)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("moulaga")

STATIC_DIR = Path(__file__).resolve().parent / "static"
REVALIDATED_STATIC_FILES = frozenset({"index.html", "manifest.webmanifest", "sw.js"})


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_dirs()
    await init_db()
    logger.info("Moulaga demarre - base SQLite initialisee")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Moulaga",
        description="Gestion personnelle de budget, comptes et transactions.",
        version="1.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(budget.router, prefix="/api")
    app.include_router(transactions.router, prefix="/api")
    app.include_router(accounts.router, prefix="/api")
    app.include_router(categories.router, prefix="/api")
    app.include_router(preferences.router, prefix="/api")
    app.include_router(budgets.router, prefix="/api")
    app.include_router(rules.router, prefix="/api")
    app.include_router(recurring.router, prefix="/api")
    app.include_router(wealth.router, prefix="/api")
    app.include_router(household.router, prefix="/api")
    app.include_router(merchants.router, prefix="/api")

    @app.get("/api/health", tags=["systeme"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    if not STATIC_DIR.exists():

        @app.get("/", include_in_schema=False)
        async def missing_frontend() -> JSONResponse:
            return JSONResponse(
                {"detail": "Interface non compilee. Lance `npm run build` dans frontend/."},
                status_code=503,
            )

        return

    assets = STATIC_DIR / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    async def spa(full_path: str) -> FileResponse | JSONResponse:
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Ressource introuvable"}, status_code=404)
        candidate = (STATIC_DIR / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(STATIC_DIR.resolve()):
            return _frontend_file_response(candidate)
        return _frontend_file_response(STATIC_DIR / "index.html")


def _frontend_file_response(path: Path) -> FileResponse:
    headers: dict[str, str] = {}
    if path.name in REVALIDATED_STATIC_FILES:
        headers["Cache-Control"] = "no-cache"
    if path.name == "sw.js":
        headers["Service-Worker-Allowed"] = "/"
    return FileResponse(path, headers=headers)


app = create_app()
