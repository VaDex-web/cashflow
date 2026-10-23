"""Логи без чувствительных данных.

Фильтр маскирует в любом сообщении токены (JWT, Bearer), ИНН (10/12 цифр), суммы, наименования в кавычках «…»
и e-mail; middleware пишет только метод, путь без query, код ответа и время.
Тела запросов, назначения платежей и названия контрагентов в логи не попадают.
"""
from __future__ import annotations

import logging
import re
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_PATTERNS = [
    (re.compile(r"(?i)bearer\s+[\w.~+/=-]+"), "Bearer <токен>"),
    (re.compile(r"\beyJ[\w-]{5,}\.[\w-]{5,}\.[\w-]{5,}"), "<токен>"),
    (re.compile(r"(?<!\d)\d{10}(?:\d{2})?(?!\d)"), "<ИНН>"),
    (re.compile(r"«[^»]{1,120}»"), "«…»"),
    (re.compile(r"\"[^\"]{1,120}\""), "\"…\""),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<email>"),
    (re.compile(r"(?<![\w/-])\d{1,3}(?:[  ]\d{3})+(?:[.,]\d{1,2})?(?!\d)"), "<сумма>"),
    (re.compile(r"(?<![\w/-])\d{4,}(?:[.,]\d{1,2})?(?![\w-])"), "<сумма>"),
    (re.compile(r"(?<![\w/-])\d+[.,]\d{2}(?!\d)"), "<сумма>"),
]


def mask(text: str) -> str:
    for rx, repl in _PATTERNS:
        text = rx.sub(repl, text)
    return text


class SensitiveDataFilter(logging.Filter):
    """Маскирует чувствительные данные в сообщении и аргументах записи лога."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            msg = str(record.msg)
        record.msg = mask(msg)
        record.args = ()
        if record.exc_text:
            record.exc_text = mask(record.exc_text)
        return True


_installed = False


def setup_logging(level: int = logging.INFO) -> None:
    global _installed
    if _installed:
        return
    flt = SensitiveDataFilter()
    root = logging.getLogger()
    if not root.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(h)
    root.setLevel(level)
    for name in ("", "api", "cashflow_core", "uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy"):
        lg = logging.getLogger(name)
        lg.addFilter(flt)
        for h in lg.handlers:
            h.addFilter(flt)
    for h in root.handlers:
        h.addFilter(flt)
    # access-лог uvicorn пишет query-строку — заменяем своим middleware
    logging.getLogger("uvicorn.access").disabled = True
    _installed = True


log = logging.getLogger("api.http")


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        t0 = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            path = request.url.path
            # id компаний оставляем, но длинные числа в пути маскирует фильтр
            log.info("%s %s %s %.0fms", request.method, path, status, (time.perf_counter() - t0) * 1000)
