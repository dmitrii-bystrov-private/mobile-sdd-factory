"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes_artifacts import router as artifacts_router
from backend.api.routes_events import router as events_router
from backend.api.routes_operator import router as operator_router
from backend.api.routes_roles import router as roles_router
from backend.api.routes_sessions import router as sessions_router
from backend.api.routes_work_items import router as work_items_router
from backend.dependencies import build_dependencies


def create_app() -> FastAPI:
    app = FastAPI(title="SDD Factory")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(127\.0\.0\.1|localhost)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.dependencies = build_dependencies()
    app.include_router(sessions_router)
    app.include_router(events_router)
    app.include_router(roles_router)
    app.include_router(artifacts_router)
    app.include_router(work_items_router)
    app.include_router(operator_router)
    return app
