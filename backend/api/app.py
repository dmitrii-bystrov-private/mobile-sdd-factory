"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from factory.disk_space import DiskSpaceGuard, disk_space_failure

from backend.api.routes_artifacts import router as artifacts_router
from backend.api.routes_events import router as events_router
from backend.api.routes_operator import router as operator_router
from backend.api.routes_roles import router as roles_router
from backend.api.routes_sessions import router as sessions_router
from backend.api.routes_work_items import router as work_items_router
from backend.dependencies import build_dependencies


def create_app() -> FastAPI:
    app = FastAPI(title="Constellation: Agent Runtime")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(127\.0\.0\.1|localhost)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    dependencies = build_dependencies()
    app.state.dependencies = dependencies

    @app.middleware("http")
    async def recover_disk_pressure(request, call_next):
        try:
            return await call_next(request)
        except Exception as error:
            if not disk_space_failure(error):
                raise
            # The failed mutation is never replayed here; the caller controls retry.
            config = dependencies.config
            guard = DiskSpaceGuard(config.workdir_root, config.repo_root, config.database_path)
            await run_in_threadpool(guard.check, force=True)
            return JSONResponse(status_code=503, content={"detail":
                "Not enough disk space to persist this operation. Low-priority task caches were checked. Free disk space, then retry the same operation."})

    loop_runner = getattr(dependencies, "loop_runner", None)
    if loop_runner is not None and hasattr(loop_runner, "start"):
        loop_runner.start()
    app.include_router(sessions_router)
    app.include_router(events_router)
    app.include_router(roles_router)
    app.include_router(artifacts_router)
    app.include_router(work_items_router)
    app.include_router(operator_router)
    return app
