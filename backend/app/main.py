import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .ai import DemoAnswerer, OpenAIAnswerer
from .config import ROOT, Settings
from .repository import FirestoreRepository, ServiceError, SQLiteRepository
from .routes import ChatRateLimit, router


def create_app(settings=None, repository=None, answerer=None):
    cfg = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = cfg
        app.state.repository = repository or (FirestoreRepository(cfg) if cfg.mode == "production" else SQLiteRepository(cfg.sqlite_path))
        app.state.answerer = answerer or (OpenAIAnswerer(cfg) if cfg.mode in {"local", "production"} else DemoAnswerer())
        app.state.rate_limit = ChatRateLimit()
        yield
        for resource in [app.state.repository, app.state.answerer]:
            if hasattr(resource, "close"):
                resource.close()

    app = FastAPI(
        title="Pulse · 서버 메트릭 AI 비서", version="1.0.0",
        description="합성 CPU·메모리 관측값 관리, 통계 요약, 데이터 기반 대화 및 기록 API. demo는 SQLite/규칙 응답, local은 SQLite/GPT API, production은 Firestore/GPT API를 사용합니다.",
        lifespan=lifespan,
    )
    app.add_middleware(CORSMiddleware, allow_origins=list(cfg.allowed_origins), allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type"])

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": "입력 형식을 확인해 주세요. 날짜는 시간대가 있는 ISO 형식, 사용률은 0~100 사이의 숫자여야 합니다.",
            "errors": [{"field": ".".join(str(loc) for loc in error["loc"]), "message": error["msg"]} for error in exc.errors()]})

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logging.getLogger(__name__).error("Request failed: %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": "서버에서 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."})

    app.include_router(router)
    app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
    return app


app = create_app()
