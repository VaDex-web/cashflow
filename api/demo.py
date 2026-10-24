"""Демо-вход в один клик: у каждого гостя — своя копия демо-компании с подготовленным прогнозом.

При старте сервера готовится скрытый шаблон ``demo-template``: копия демо-компании (``DEMO_COMPANY``, по умолчанию
S02) с подключёнными источниками и посчитанным прогнозом. Его владелец — служебный пользователь, поэтому снаружи
он недоступен и гости его не меняют. ``POST /api/auth/demo`` создаёт гостя и клонирует в его компанию строки
шаблона вместе с сохранённым состоянием прогноза — первый экран открывается без пересчёта.

Компании датасета и синтетики — общие и только для чтения: кто выбирает такую компанию как свою, получает
личную копию (:func:`personal_copy`), поэтому действия одного посетителя не видны другим.
"""
from __future__ import annotations

import datetime as dt
import logging
import secrets
import time
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import services as svc
from .config import get_settings
from .db import (Company, CounterpartyCheck, Document, EventRow, ForecastStateRow, IntegrationRun, Transaction, User,
                 utcnow)
from .security import hash_password

log = logging.getLogger("api.demo")

TEMPLATE_ID = "demo-template"
SYSTEM_OWNER = "__system__"
GUEST_PREFIX = "guest-"
#: источники, которые подключаются в демо (тестовые данные — data/synthetic/integrations/<компания>/)
DEMO_SOURCES = ("tax_calendar", "1c", "bank", "registry")
_CHILDREN = (Transaction, EventRow, CounterpartyCheck, Document, IntegrationRun)


def _copy_row(row: Any, **override: Any) -> Any:
    cls = type(row)
    data = {c.key: getattr(row, c.key) for c in cls.__mapper__.column_attrs}
    for pk in cls.__mapper__.primary_key:
        if pk.key != "company_id":
            data.pop(pk.key, None)
    data.update(override)
    return cls(**data)


def _clone_company(session: Session, src: Company, new_id: str, owner: str, origin: str) -> Company:
    c = _copy_row(src, id=new_id, owner=owner, origin=origin, created_at=utcnow(),
                  settings=dict(src.settings or {}, dataset_id=(src.settings or {}).get("dataset_id") or src.id))
    session.add(c)
    session.flush()
    for model in _CHILDREN:
        for row in session.scalars(select(model).where(model.company_id == src.id)):
            session.add(_copy_row(row, company_id=new_id))
    st = session.get(ForecastStateRow, src.id)
    if st is not None:
        session.add(_copy_row(st, company_id=new_id))
    session.commit()
    return c


def prepare_template(session: Session) -> Company | None:
    """Шаблон демо: копия демо-компании, источники подключены, прогноз посчитан и сохранён."""
    s = get_settings()
    if not s.demo_company:
        return None
    t0 = time.perf_counter()
    tpl = session.get(Company, TEMPLATE_ID)
    if tpl is None:
        src = svc.get_company(session, s.demo_company, SYSTEM_OWNER)
        tpl = _clone_company(session, src, TEMPLATE_ID, SYSTEM_OWNER, "demo")
    done = {r.name for r in session.scalars(select(IntegrationRun).where(IntegrationRun.company_id == TEMPLATE_ID))}
    for name in DEMO_SOURCES:
        if name not in done:
            svc.sync(session, tpl, name)
    svc.forecast(session, tpl, s.default_horizon)
    log.info("demo template ready in %.1fs", time.perf_counter() - t0)
    return tpl


def cleanup_guests(session: Session) -> int:
    """Удалить гостей старше DEMO_TTL_HOURS вместе с их компаниями (каскадом)."""
    cutoff = utcnow() - dt.timedelta(hours=get_settings().demo_ttl_hours)
    old = list(session.scalars(select(User).where(User.username.like(f"{GUEST_PREFIX}%"), User.created_at < cutoff)))
    if not old:
        return 0
    names = [u.username for u in old]
    session.execute(delete(Company).where(Company.owner.in_(names)))
    session.execute(delete(User).where(User.username.in_(names)))
    session.commit()
    return len(names)


def personal_copy(session: Session, user: str, src: Company) -> Company:
    """Личная копия общей компании для пользователя (одна на источник: повторный выбор открывает ту же копию)."""
    for c in session.scalars(select(Company).where(Company.owner == user, Company.origin == "copy")):
        if (c.settings or {}).get("dataset_id") == src.id:
            return c
    return _clone_company(session, src, f"{src.id.lower()}-{secrets.token_hex(3)}", user, "copy")


def personalize_users(session: Session) -> int:
    """Пользователям из API_USERS с общей компанией (``demo:demo:S02``) — своя копия: общие компании только для чтения."""
    n = 0
    for u in list(session.scalars(select(User).where(User.company_id.is_not(None)))):
        if u.username == SYSTEM_OWNER or u.username.startswith(GUEST_PREFIX):
            continue
        try:
            c = svc.get_company(session, u.company_id, u.username)
        except Exception:  # noqa: BLE001 — компании нет (файл не найден): оставляем как есть
            continue
        if c.owner is None:
            u.company_id = personal_copy(session, u.username, c).id
            n += 1
    session.commit()
    return n


def create_guest(session: Session) -> str:
    """Новый гость со своей копией демо-компании; возвращает логин."""
    cleanup_guests(session)
    tpl = session.get(Company, TEMPLATE_ID) or prepare_template(session)
    if tpl is None:
        raise RuntimeError("демо-компания не настроена (DEMO_COMPANY)")
    login = GUEST_PREFIX + secrets.token_hex(6)
    base = (tpl.settings or {}).get("dataset_id") or "demo"
    cid = f"{base.lower()}-{secrets.token_hex(3)}"
    session.add(User(username=login, password_hash=hash_password(secrets.token_urlsafe(24)), company_id=cid))
    session.flush()
    _clone_company(session, tpl, cid, login, "demo")
    return login
