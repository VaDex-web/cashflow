"""Хранилище: SQLite через SQLAlchemy — компании, операции, события, проверки контрагентов, состояние прогноза."""
from __future__ import annotations

import datetime as dt
from typing import Any, Iterator, Optional

from sqlalchemy import (JSON, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint,
                        create_engine, event)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import get_settings


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    #: один пользователь = одна компания: та, что открывается после входа
    company_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    inn: Mapped[str] = mapped_column(String(16), default="")
    legal_form: Mapped[str] = mapped_column(String(16), default="")
    industry: Mapped[str] = mapped_column(String(128), default="")
    #: владелец (логин); None — общая компания из датасета/синтетики
    owner: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    origin: Mapped[str] = mapped_column(String(16), default="upload")       # upload | dataset | synthetic
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)     # налоговый режим и т.п.
    tx_version: Mapped[int] = mapped_column(Integer, default=0)              # растёт при новых операциях
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)          # предупреждения парсера
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(3))
    counterparty_name: Mapped[str] = mapped_column(String(256), default="")
    counterparty_inn: Mapped[str] = mapped_column(String(16), default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    balance_eod: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    batch: Mapped[int] = mapped_column(Integer, default=0)                   # 0 — выписка, n — POST /transactions


class EventRow(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("company_id", "id", name="uq_event"),)
    pk: Mapped[int] = mapped_column(Integer, primary_key=True)
    id: Mapped[str] = mapped_column(String(96), index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(16))
    direction: Mapped[str] = mapped_column(String(3))
    amount: Mapped[float] = mapped_column(Float)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="expected")
    counterparty: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    counterparty_inn: Mapped[str] = mapped_column(String(16), default="")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: какая интеграция создала событие: tax_calendar, 1c, bank, registry, contracts, invoices, manual
    origin: Mapped[str] = mapped_column(String(16), default="manual")
    #: статус выставлен пользователем вручную — синхронизация его не перетирает
    status_locked: Mapped[bool] = mapped_column(default=False)
    #: фактическая оплата (план-факт): дата и сумма
    paid_date: Mapped[Optional[dt.date]] = mapped_column(Date, nullable=True)
    paid_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CounterpartyCheck(Base):
    """Результат проверки контрагента по открытым реестрам."""

    __tablename__ = "counterparty_checks"
    __table_args__ = (UniqueConstraint("company_id", "inn", name="uq_cp_check"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    inn: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(256), default="")
    risk_level: Mapped[str] = mapped_column(String(8), default="low")       # low | medium | high
    delay_days: Mapped[int] = mapped_column(Integer, default=0)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    checked_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IntegrationRun(Base):
    __tablename__ = "integration_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(16))
    synced_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    events_added: Mapped[int] = mapped_column(Integer, default=0)
    events_updated: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")


class Document(Base):
    """Загруженный файл источника (выгрузка 1С, договоры, счета, данные банка/реестров)."""

    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("company_id", "kind", name="uq_doc"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    filename: Mapped[str] = mapped_column(String(256), default="")
    content: Mapped[bytes] = mapped_column(LargeBinary)
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ForecastStateRow(Base):
    """Сохранённое состояние ядра (для update_forecast без полного пересчёта) и последний прогноз."""

    __tablename__ = "forecast_states"
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(128))
    blob: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)            # предупреждения API (просрочки и т.п.)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


_engine = None
_Session: sessionmaker | None = None


def init_db(url: str | None = None) -> None:
    global _engine, _Session
    url = url or get_settings().database_url
    kw: dict[str, Any] = {}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(url, **kw)
    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _fk(dbapi_conn, _):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
    Base.metadata.create_all(_engine)
    _migrate(_engine)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False)


def _migrate(engine: Any) -> None:
    """Добавить новые колонки в уже созданную базу (SQLite не делает этого в create_all)."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in have and col.nullable:
                with engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}'))


def get_session() -> Iterator[Session]:
    if _Session is None:
        init_db()
    assert _Session is not None
    s = _Session()
    try:
        yield s
    finally:
        s.close()


def new_session() -> Session:
    if _Session is None:
        init_db()
    assert _Session is not None
    return _Session()
