from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.admin import router as admin_router
from app.admin_operations import router as admin_operations_router
from app.auth import router
from app.avatars import router as avatars_router
from app.config import Settings
from app.db import make_engine, session_factory
from app.errors import error_response, install_error_handlers
from app.generation import GenerationRunner
from app.mail import SMTPMailer
from app.maintenance import MaintenanceRunner
from app.materials import router as materials_router
from app.speech_service import LocalSpeech
from app.training_api import router as training_router


def create_app(settings: Settings | None = None, *, mailer=None, gateway_factory=None, speech=None) -> FastAPI:
    settings = settings or Settings()
    application = FastAPI(
        title="CareerPilot API", version="0.1.0",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )
    engine = make_engine(settings)
    application.state.settings = settings
    application.state.engine = engine
    application.state.session_factory = session_factory(engine) if engine is not None else None
    application.state.mailer = mailer or SMTPMailer(settings)
    application.state.generation = GenerationRunner(engine, settings, gateway_factory)
    application.state.speech = speech or LocalSpeech(settings)
    application.state.maintenance = MaintenanceRunner(engine, settings)
    @asynccontextmanager
    async def lifespan(_):
        application.state.maintenance.start()
        yield
        application.state.generation.close()
        application.state.maintenance.close()
    application.router.lifespan_context = lifespan
    install_error_handlers(application)

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        origin = request.headers.get("origin")
        same_origin = f"{request.url.scheme}://{request.url.netloc}"
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
            if origin not in settings.allowed_origins and origin != same_origin:
                response = error_response(request, 403, "ORIGIN_FORBIDDEN", "请求来源不被允许")
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    application.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    application.add_middleware(
        CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key", "X-Training-Lease"], expose_headers=["X-Request-ID"],
    )

    @application.get("/health/live", tags=["health"])
    def live():
        return {"status": "ok", "service": "careerpilot-backend"}

    @application.get("/health/ready", tags=["health"])
    def ready(request: Request):
        if engine is None or not settings.secret_key:
            return error_response(request, 503, "SERVICE_NOT_CONFIGURED", "数据库或认证密钥尚未配置")
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1 FROM users LIMIT 1"))
        except SQLAlchemyError:
            return error_response(request, 503, "DATABASE_NOT_READY", "数据库未就绪或迁移尚未执行", True)
        return {"status": "ready"}

    application.include_router(router)
    application.include_router(avatars_router)
    application.include_router(materials_router)
    application.include_router(admin_router)
    application.include_router(admin_operations_router)
    application.include_router(training_router)
    return application


app = create_app()

