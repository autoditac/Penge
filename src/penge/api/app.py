"""FastAPI application factory for the Penge read API."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from penge.api.imports.routes import router as imports_router
from penge.api.routes import router

# Vite's dev server origins; override for other setups via
# PENGE_API_CORS_ORIGINS (comma-separated). The API itself is
# local-only (binds 127.0.0.1 by default, see __main__).
_DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


def cors_origins() -> list[str]:
    """Return the allowed CORS origins from the environment."""
    raw = os.environ.get("PENGE_API_CORS_ORIGINS", _DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app() -> FastAPI:
    """Build the FastAPI application with routes and CORS configured."""
    app = FastAPI(
        title="Penge read API",
        version="1.0.0",
        description=(
            "Read-only JSON API over the Penge analytics marts. "
            "All amounts are reported in EUR and DKK in parallel; "
            "account identifiers are masked server-side. "
            "The /imports endpoints are the one write surface: staged "
            "import sessions per ADR-0037."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        # GET for the read surface; POST/PATCH/DELETE only exist under
        # /imports (staged import sessions, ADR-0037).
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(imports_router)
    return app
