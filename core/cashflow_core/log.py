from __future__ import annotations

import logging
import re

_INN_RE = re.compile(r"\b\d{10}(\d{2})?\b")
_MONEY_RE = re.compile(r"(?<![\d\-:])\d[\d  ]{3,}(?:[.,]\d{1,2})?(?![\d\-:])\s*(?:₽|руб|rub)?", re.IGNORECASE)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        msg = _INN_RE.sub("<inn>", msg)
        msg = _MONEY_RE.sub("<num>", msg)
        record.msg, record.args = msg, ()
        return True


def get_logger(name: str = "cashflow_core") -> logging.Logger:
    logger = logging.getLogger(name)
    if not any(isinstance(f, RedactFilter) for f in logger.filters):
        logger.addFilter(RedactFilter())
    return logger
