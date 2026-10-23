"""Безопасное логирование: только агрегаты и идентификаторы.

В логи нельзя писать ИНН, названия контрагентов, назначения платежей и суммы
отдельных операций. Все модули пишут через :func:`get_logger`, а сообщения
формируют только из счётчиков, долей, длительностей и id. Дополнительно
фильтр :class:`RedactFilter` вырезает похожие на ИНН и суммы числа, если
кто-то случайно их передаст.
"""
from __future__ import annotations

import logging
import re

_INN_RE = re.compile(r"\b\d{10}(\d{2})?\b")
_MONEY_RE = re.compile(r"(?<![\d\-:])\d[\d  ]{3,}(?:[.,]\d{1,2})?(?![\d\-:])\s*(?:₽|руб|rub)?", re.IGNORECASE)


class RedactFilter(logging.Filter):
    """Маскирует ИНН и денежные суммы в тексте сообщения лога."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        msg = record.getMessage()
        msg = _INN_RE.sub("<inn>", msg)
        msg = _MONEY_RE.sub("<num>", msg)
        record.msg, record.args = msg, ()
        return True


def get_logger(name: str = "cashflow_core") -> logging.Logger:
    """Логгер пакета с фильтром маскировки."""
    logger = logging.getLogger(name)
    if not any(isinstance(f, RedactFilter) for f in logger.filters):
        logger.addFilter(RedactFilter())
    return logger
