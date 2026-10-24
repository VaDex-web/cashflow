from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import get_settings
from .core_adapter import get_core
from .db import init_db, new_session
from .logging_setup import AccessLogMiddleware, setup_logging
from .ratelimit import RateLimitMiddleware
from .routes import router
from .security import ensure_users

log = logging.getLogger("api")

_FIELD_RU = {"amount": "сумма", "date": "дата", "direction": "направление", "type": "тип", "source": "источник",
             "status": "статус", "username": "логин", "password": "пароль", "file": "файл", "params": "параметры",
             "horizon": "горизонт", "text": "текст"}


def _validation_text(exc: RequestValidationError) -> str:
    parts = []
    for e in exc.errors()[:5]:
        loc = [str(x) for x in e.get("loc", []) if x not in ("body", "query", "path")]
        field = _FIELD_RU.get(loc[-1], loc[-1]) if loc else ""
        t = e.get("type", "")
        msg = str(e.get("msg", ""))
        if msg.startswith("Value error, "):
            parts.append(msg.removeprefix("Value error, "))
            continue
        if t == "missing":
            text = "обязательное поле"
        elif t in ("greater_than", "greater_than_equal"):
            text = f"должно быть не меньше {e.get('ctx', {}).get('gt', e.get('ctx', {}).get('ge', ''))}".replace("не меньше 0", "больше 0")
        elif t in ("less_than_equal", "less_than"):
            text = f"должно быть не больше {e.get('ctx', {}).get('le', e.get('ctx', {}).get('lt', ''))}"
        elif t.startswith("date"):
            text = "дата в формате ГГГГ-ММ-ДД"
        elif t == "literal_error":
            text = "допустимые значения: " + str(e.get("ctx", {}).get("expected", ""))
        elif t in ("float_parsing", "int_parsing"):
            text = "должно быть числом"
        else:
            text = "неверное значение"
        parts.append(f"{field}: {text}" if field else text)
    return "Проверьте данные — " + "; ".join(parts)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    with new_session() as s:
        ensure_users(s)
    core = get_core()
    from .demo import personalize_users

    with new_session() as s:
        personalize_users(s)
    if get_settings().demo_warmup:
        from .demo import prepare_template

        with new_session() as s:
            try:
                prepare_template(s)
            except Exception as exc:
                log.warning("demo warmup failed: %s", type(exc).__name__)
    log.info("api started: core=%s", core.name)
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Денежный прогноз — API",
        description="Прогноз остатка на счёте малого бизнеса, кассовые разрывы, сценарии «что если», план-факт и источники "
                    "данных. Контракт — docs/contract.md. Все эндпоинты, кроме /api/health, /api/auth/login и /api/auth/demo, требуют "
                    "заголовок `Authorization: Bearer <token>` (кнопка Authorize).",
        version="1.0.0", lifespan=lifespan)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True, allow_methods=["*"],
                       allow_headers=["*"])

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": _validation_text(exc)})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if detail in ("Not Found", "Method Not Allowed", "Unauthorized", "Forbidden"):
            detail = {404: "Не найдено", 405: "Метод не поддерживается", 401: "Нужно войти в систему",
                      403: "Нет доступа"}.get(exc.status_code, detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled error: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "Ошибка на сервере. Попробуйте ещё раз через минуту."})

    app.include_router(router)
    return app


app = create_app()
