"""Бизнес-логика API: компании, операции, события, состояние прогноза, интеграции, план-факт."""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import logging
import pickle
import secrets
import threading
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import plan_fact as pf
from .config import get_settings
from .core_adapter import events_for_core, get_core, registry_delay
from .db import (Company, CounterpartyCheck, Document, EventRow, ForecastStateRow, IntegrationRun, Transaction, User,
                 utcnow)
from .integrations import CompanyContext, SourceEvent, all_integrations
from .schemas import Event, EventCreate, EventUpdate
from .statements import (StatementError, check_header, companies_in_file, frame_from_core, normalize_row,
                         parse_statement_bytes, select_company)
from .textfmt import day_month, rub

log = logging.getLogger("api.service")

_cache: dict[str, tuple[str, Any]] = {}          # company_id → (ключ, состояние ядра)
_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)


def reset_cache() -> None:
    _cache.clear()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- справочники датасета
def _read_companies_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


def known_companies() -> list[dict[str, Any]]:
    """Компании из data/raw/companies.csv и data/synthetic/companies.csv."""
    s = get_settings()
    out = []
    for origin, base in (("dataset", s.raw_dir), ("synthetic", s.synthetic_dir)):
        for r in _read_companies_csv(base / "companies.csv"):
            r["_origin"] = origin
            r["_path"] = str(base / "statements" / f"{r['company_id']}.csv")
            out.append(r)
    return out


def _known(cid: str) -> dict[str, Any] | None:
    return next((r for r in known_companies() if r["company_id"] == cid), None)


# --------------------------------------------------------------------------- компании и операции
def _parse(raw: bytes, company: str | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Проверка файла + чистка ядром (или собственным разбором в режиме заглушки)."""
    check_header(raw)
    core = get_core()
    if core.name == "stub":
        return parse_statement_bytes(raw, company)
    df = core.load_statement(io.BytesIO(raw))
    warnings = list(df.attrs.get("warnings", []))
    if not len(df):
        raise StatementError("Не удалось прочитать операции. " + " ".join(warnings[:3]))
    return frame_from_core(df), warnings


def _store_rows(session: Session, company_id: str, rows: Iterable[dict[str, Any]], batch: int) -> int:
    n = 0
    for r in rows:
        session.add(Transaction(company_id=company_id, date=r["date"], amount=float(r["amount"]), direction=r["direction"],
                                counterparty_name=r.get("counterparty_name") or "", counterparty_inn=r.get("counterparty_inn") or "",
                                purpose=r.get("purpose") or "", balance_eod=r.get("balance_eod"), batch=batch))
        n += 1
    return n


def import_known(session: Session, cid: str) -> Company | None:
    """Компания из датасета/синтетики: загружается из файла при первом обращении."""
    meta = _known(cid)
    if meta is None or not Path(meta["_path"]).exists():
        return None
    raw = Path(meta["_path"]).read_bytes()
    try:
        rows, warnings = _parse(raw)
    except StatementError as exc:
        raise HTTPException(422, f"Выписку {cid} не удалось прочитать: {exc}") from None
    c = Company(id=cid, name=meta.get("company_name", cid), inn=meta.get("company_inn", ""),
                legal_form=meta.get("legal_form", ""), industry=meta.get("industry", ""), owner=None,
                origin=meta["_origin"], settings={"dataset_id": cid}, warnings=warnings)
    session.add(c)
    session.flush()
    _store_rows(session, cid, rows, 0)
    session.commit()
    log.info("company imported: %s rows=%d", cid, len(rows))
    return c


def get_company(session: Session, cid: str, user: str, write: bool = False) -> Company:
    """Компания с проверкой доступа; ``write=True`` — для изменений (общие компании только для чтения)."""
    from .security import check_access

    with _locks[f"import:{cid}"]:
        c = session.get(Company, cid)
        if c is None:
            c = import_known(session, cid)
    return check_access(c, user, write)


def create_company(session: Session, raw: bytes, filename: str, user: str, company: str | None) -> tuple[Company, int, list[str]]:
    ids = companies_in_file(raw)
    if len(ids) > 1:
        if not company:
            raise StatementError(f"В файле операции нескольких компаний ({', '.join(ids[:5])}{'…' if len(ids) > 5 else ''}). "
                                 f"Загрузите выписку одной компании или укажите параметр ?company=…")
        if company not in ids:
            raise StatementError(f"Компании {company} нет в файле.")
        raw = select_company(raw, company)
        ids = [company]
    rows, warnings = _parse(raw)
    src_id = ids[0] if ids else ""
    meta = _known(src_id) if src_id else None
    cid = f"{(src_id or 'c').lower()}-{secrets.token_hex(3)}"
    stem = Path(filename or "").stem
    c = Company(id=cid, name=(meta or {}).get("company_name") or stem or "Моя компания", inn=(meta or {}).get("company_inn", ""),
                legal_form=(meta or {}).get("legal_form", ""), industry=(meta or {}).get("industry", "Загружено пользователем"),
                owner=user, origin="upload", settings={"dataset_id": src_id} if src_id else {}, warnings=warnings)
    session.add(c)
    session.flush()
    n = _store_rows(session, cid, rows, 0)
    _user(session, user).company_id = cid        # один пользователь = одна компания: новая выписка — его компания
    session.commit()
    log.info("company uploaded: %s rows=%d", cid, n)
    return c, n, warnings


def _company_info(session: Session, c: Company) -> dict[str, Any]:
    stats = session.execute(select(func.min(Transaction.date), func.max(Transaction.date), func.count())
                            .where(Transaction.company_id == c.id)).one()
    return {"company_id": c.id, "company_name": c.name, "legal_form": c.legal_form, "industry": c.industry,
            "first_operation_date": stats[0].isoformat() if stats[0] else None,
            "last_operation_date": stats[1].isoformat() if stats[1] else None, "operations_count": int(stats[2])}


def _user(session: Session, username: str) -> User:
    u = session.scalar(select(User).where(User.username == username))
    if u is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден — войдите заново")
    return u


def list_companies(session: Session, user: str, demo: bool = False) -> list[dict[str, Any]]:
    """Один пользователь = одна компания. Список компаний датасета и демо — только в демо-режиме (``demo=true``)."""
    out = []
    u = _user(session, user)
    if u.company_id:
        try:
            out.append(_company_info(session, get_company(session, u.company_id, user)))
        except HTTPException:
            pass
    if demo:
        mine = {x["company_id"] for x in out}
        for r in known_companies():
            if r["company_id"] in mine:
                continue
            out.append({"company_id": r["company_id"], "company_name": r.get("company_name", ""),
                        "legal_form": r.get("legal_form", ""), "industry": r.get("industry", ""),
                        "first_operation_date": r.get("first_operation_date") or None,
                        "last_operation_date": r.get("last_operation_date") or None,
                        "operations_count": int(r.get("operations_count") or 0)})
    return out


def me(session: Session, user: str) -> dict[str, Any]:
    u = _user(session, user)
    name = None
    if u.company_id:
        c = session.get(Company, u.company_id)
        meta = None if c else _known(u.company_id)
        name = c.name if c else (meta or {}).get("company_name")
    return {"username": u.username, "company_id": u.company_id, "company_name": name}


def set_my_company(session: Session, user: str, cid: str) -> dict[str, Any]:
    """Демо-переключатель: сделать компанию «моей». Общая компания (датасет, демо) не меняется —
    пользователь получает свою копию, и все его изменения остаются в ней."""
    from .demo import personal_copy

    c = get_company(session, cid, user)
    if c.owner is None:
        c = personal_copy(session, user, c)
    u = _user(session, user)
    u.company_id = c.id
    session.commit()
    return me(session, user)


def company_df(session: Session, company: Company) -> pd.DataFrame:
    rows = session.execute(select(Transaction.date, Transaction.amount, Transaction.direction, Transaction.counterparty_name,
                                  Transaction.counterparty_inn, Transaction.purpose, Transaction.balance_eod)
                           .where(Transaction.company_id == company.id).order_by(Transaction.date, Transaction.id)).all()
    df = pd.DataFrame(rows, columns=["date", "amount", "direction", "counterparty_name", "counterparty_inn", "purpose", "balance_eod"])
    if len(df):
        df["date"] = pd.to_datetime(df["date"])
    return df


def as_of_of(session: Session, company: Company) -> date | None:
    return session.scalar(select(func.max(Transaction.date)).where(Transaction.company_id == company.id))


# --------------------------------------------------------------------------- события
def to_event(r: EventRow) -> Event:
    return Event(id=r.id, type=r.type, direction=r.direction, amount=r.amount, date=r.date, source=r.source,
                 status=r.status, counterparty=r.counterparty, note=r.note)


def event_rows(session: Session, company: Company) -> list[EventRow]:
    return list(session.scalars(select(EventRow).where(EventRow.company_id == company.id).order_by(EventRow.date, EventRow.pk)))


def get_event_row(session: Session, company: Company, event_id: str) -> EventRow:
    r = session.scalar(select(EventRow).where(EventRow.company_id == company.id, EventRow.id == event_id))
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено")
    return r


def create_event(session: Session, company: Company, ev: EventCreate) -> Event:
    eid = f"man-{secrets.token_hex(4)}"
    r = EventRow(id=eid, company_id=company.id, type=ev.type, direction=ev.direction, amount=ev.amount, date=ev.date,
                 source=ev.source, status=ev.status, counterparty=ev.counterparty, note=ev.note, origin="manual",
                 status_locked=ev.status != "expected")
    session.add(r)
    session.commit()
    invalidate(company.id)
    return to_event(r)


def update_event(session: Session, company: Company, event_id: str, upd: EventUpdate) -> Event:
    r = get_event_row(session, company, event_id)
    data = upd.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(r, k, v)
    if "status" in data:
        r.status_locked = True
    session.commit()
    invalidate(company.id)
    return to_event(r)


def delete_event(session: Session, company: Company, event_id: str) -> None:
    r = get_event_row(session, company, event_id)
    session.delete(r)
    session.commit()
    invalidate(company.id)


def _dup_of(rows: list[EventRow], e: SourceEvent, origin: str) -> EventRow | None:
    """То же событие из другого источника (зарплата из 1С и из банка, платёжка = счёт поставщика)."""
    for r in rows:
        if r.origin == origin or r.direction != e.direction:
            continue
        if abs((r.date - e.date).days) <= 2 and abs(r.amount - e.amount) <= 0.01 * max(e.amount, 1.0):
            same_cp = not e.counterparty or not r.counterparty or \
                pf._norm(r.counterparty) == pf._norm(e.counterparty) or (e.counterparty_inn and e.counterparty_inn == r.counterparty_inn)
            if same_cp or r.type == e.type:
                return r
    return None


def upsert_events(session: Session, company: Company, events: list[SourceEvent], origin: str) -> tuple[int, int]:
    rows = event_rows(session, company)
    by_id = {r.id: r for r in rows}
    added = updated = 0
    for e in events:
        r = by_id.get(e.id)
        if r is None:
            if _dup_of(rows, e, origin) is not None:
                continue
            r = EventRow(id=e.id, company_id=company.id, type=e.type, direction=e.direction, amount=e.amount, date=e.date,
                         source=e.source, status=e.status, counterparty=e.counterparty, counterparty_inn=e.counterparty_inn,
                         note=e.note, origin=origin)
            session.add(r)
            rows.append(r)
            by_id[e.id] = r
            added += 1
            continue
        changed = False
        for k in ("type", "direction", "amount", "date", "source", "counterparty", "note", "counterparty_inn"):
            v = getattr(e, k)
            if getattr(r, k) != v:
                setattr(r, k, v)
                changed = True
        if not r.status_locked and r.status != "paid" and r.status != e.status and e.status == "paid":
            r.status = "paid"
            changed = True
        updated += changed
    session.commit()
    return added, updated


def checks_map(session: Session, company: Company) -> dict[str, dict[str, Any]]:
    out = {}
    for c in session.scalars(select(CounterpartyCheck).where(CounterpartyCheck.company_id == company.id)):
        out[c.inn or c.name] = {"inn": c.inn, "name": c.name, "risk_level": c.risk_level, "delay_days": c.delay_days,
                                "reasons": c.reasons}
    return out


# --------------------------------------------------------------------------- контекст для интеграций
def context(session: Session, company: Company, df: pd.DataFrame | None = None) -> CompanyContext:
    s = get_settings()
    docs = {d.kind: d.content for d in session.scalars(select(Document).where(Document.company_id == company.id))}
    ds = (company.settings or {}).get("dataset_id") or company.id
    fx = s.synthetic_dir / "integrations" / ds
    df = company_df(session, company) if df is None else df
    return CompanyContext(company_id=company.id, name=company.name, inn=company.inn, legal_form=company.legal_form,
                          industry=company.industry, df=df, as_of=as_of_of(session, company),
                          settings=dict(company.settings or {}), documents=docs, fixtures_dir=fx if fx.exists() else None,
                          core=get_core())


# --------------------------------------------------------------------------- настройки владельца
TAX_REGIMES = ("usn_income", "usn_income_expense", "osno", "eshn")


def default_cushion(df: pd.DataFrame) -> float:
    """Комфортный минимум по умолчанию — расходы примерно за 7 дней (средние за последние 90 дней,
    без переводов между своими счетами)."""
    if df is None or not len(df):
        return 0.0
    d = df[(df["direction"] == "out") & ~df["purpose"].astype(str).str.contains("собственн", case=False, regex=False)]
    if not len(d):
        return 0.0
    dates = pd.to_datetime(df["date"])
    end = dates.max()
    start = max(dates.min(), end - pd.Timedelta(days=89))
    days = max(1, (end - start).days + 1)
    recent = d[pd.to_datetime(d["date"]) >= start]
    return float(round(recent["amount"].sum() / days * 7, -3))


def cushion_of(session: Session, company: Company, df: pd.DataFrame | None = None) -> tuple[float, float, bool]:
    """(действующий порог, порог по умолчанию, задан ли владельцем)."""
    st = company.settings or {}
    custom = st.get("safety_cushion")
    default = default_cushion(company_df(session, company) if df is None else df)
    if custom is not None:
        return float(custom), default, True
    return default, default, False


def company_settings(session: Session, company: Company) -> dict[str, Any]:
    eff, default, custom = cushion_of(session, company)
    regime = (company.settings or {}).get("tax_regime")
    est = None
    try:
        from .integrations import TaxCalendar

        est = TaxCalendar().regime(context(session, company))
    except Exception:  # noqa: BLE001
        est = None
    return {"safety_cushion": eff, "safety_cushion_default": default, "safety_cushion_custom": custom,
            "tax_regime": regime, "tax_regime_estimated": est}


def update_settings(session: Session, company: Company, data: dict[str, Any]) -> dict[str, Any]:
    st = dict(company.settings or {})
    if "safety_cushion" in data:
        v = data["safety_cushion"]
        st["safety_cushion"] = None if v is None else float(v)
    if "tax_regime" in data:
        v = data["tax_regime"]
        if v is not None and v not in TAX_REGIMES:
            raise HTTPException(422, "Налоговый режим: usn_income (УСН 6%), usn_income_expense (УСН 15%), osno (ОСНО) или eshn (ЕСХН)")
        st["tax_regime"] = v
    company.settings = st
    session.commit()
    invalidate(company.id)
    return company_settings(session, company)


# --------------------------------------------------------------------------- состояние прогноза
def _event_dicts(rows: list[EventRow]) -> list[dict[str, Any]]:
    return [{"id": r.id, "type": r.type, "direction": r.direction, "amount": r.amount, "date": r.date.isoformat(),
             "source": r.source, "status": r.status, "counterparty": r.counterparty, "note": r.note,
             "counterparty_inn": r.counterparty_inn} for r in rows]


def _key(company: Company, events: list[dict[str, Any]], checks: dict[str, Any], horizon: int, cushion: float = 0.0) -> str:
    # "risk-v2": порог разрыва 0 ₽ + комфортный минимум отдельно — старые сохранённые состояния пересобираются
    blob = json.dumps(["risk-v2", events, checks, horizon, get_settings().registry_delay_days, round(cushion, 2)], sort_keys=True,
                      ensure_ascii=False, default=str)
    return f"{get_core().name}:{company.tx_version}:{hashlib.sha1(blob.encode()).hexdigest()[:16]}"


def invalidate(company_id: str) -> None:
    """События или проверки изменились: следующий прогноз пересоберёт состояние (категоризатор переиспользуется)."""
    item = _cache.get(company_id)
    if item:
        _cache[company_id] = ("stale:" + item[0], item[1])


def _state_horizon(horizon: int) -> int:
    return max(30, min(int(horizon), 365))


def get_state(session: Session, company: Company, horizon: int = 30) -> tuple[Any, list[str]]:
    core = get_core()
    rows = event_rows(session, company)
    checks = checks_map(session, company)
    ev = _event_dicts(rows)
    H = _state_horizon(max(horizon, 30))
    cushion = cushion_of(session, company)[0]
    key = _key(company, ev, checks, H, cushion)
    core_events = events_for_core(ev, checks)
    notes: list[str] = []
    with _locks[company.id]:
        item = _cache.get(company.id)
        if item and item[0] == key:
            return item[1], notes
        st_row = session.get(ForecastStateRow, company.id)
        if st_row is not None and st_row.key == key and st_row.blob:
            try:
                state = pickle.loads(st_row.blob)
                _cache[company.id] = (key, state)
                return state, notes
            except Exception:  # noqa: BLE001 — устаревший формат состояния: пересоберём
                log.warning("state unpickle failed for %s", company.id)
        base = None
        if item and item[0].split(":")[-2] == str(company.tx_version) and not isinstance(item[1], dict):
            base = item[1]
        df = company_df(session, company) if base is None else pd.DataFrame()
        state = core.build(df, core_events, H, company.id, base_state=base, comfort_balance=cushion)
        _cache[company.id] = (key, state)
        _save_state(session, company, key, state)
        return state, notes


def _save_state(session: Session, company: Company, key: str, state: Any, result: dict[str, Any] | None = None) -> None:
    try:
        blob = pickle.dumps(state)
    except Exception:  # noqa: BLE001
        blob = None
    row = session.get(ForecastStateRow, company.id)
    if row is None:
        row = ForecastStateRow(company_id=company.id, key=key, blob=blob, notes=[])
        session.add(row)
    else:
        row.key, row.blob = key, blob
    if result is not None:
        row.result = result
    session.commit()


def _api_notes(session: Session, company: Company) -> list[str]:
    row = session.get(ForecastStateRow, company.id)
    return list(row.notes or []) if row else []


def add_note(session: Session, company: Company, text: str) -> None:
    row = session.get(ForecastStateRow, company.id)
    if row is None:
        row = ForecastStateRow(company_id=company.id, key="", blob=None, notes=[])
        session.add(row)
    notes = [n for n in (row.notes or []) if n != text][-4:]
    row.notes = notes + [text]
    session.commit()


def _finish(result: dict[str, Any], company: Company, extra: list[str]) -> dict[str, Any]:
    r = dict(result)
    r["company_id"] = company.id
    warnings = list(dict.fromkeys(list(company.warnings or [])[:3] + list(r.get("warnings") or []) + extra))
    r["warnings"] = warnings
    return r


def forecast(session: Session, company: Company, horizon: int = 30) -> dict[str, Any]:
    horizon = max(7, min(int(horizon or 30), 365))
    state, notes = get_state(session, company, horizon)
    adj, adj_notes = _registry_adjustment(session, company)
    res = _finish(get_core().forecast(state, horizon, adj), company,
                  notes + adj_notes + _cushion_note(session, company) + _api_notes(session, company))
    row = session.get(ForecastStateRow, company.id)
    if row is not None and horizon == 30:
        row.result = {"risks": res.get("risks", []), "generated_at": res.get("generated_at")}
        session.commit()
    return res


def _cushion_note(session: Session, company: Company) -> list[str]:
    eff, default, custom = cushion_of(session, company)
    if eff <= 0:
        return []
    how = "вы задали сами" if custom else "по умолчанию — расходы примерно за 7 дней"
    return [f"Кассовый разрыв — когда на счёте меньше 0 ₽. Отдельно предупреждаем, если остаток опустится ниже вашего "
            f"комфортного минимума — {rub(eff)} ({how}); изменить можно в настройках."]


def _registry_adjustment(session: Session, company: Company) -> tuple[dict[str, Any] | None, list[str]]:
    checks = checks_map(session, company)
    if not any(c.get("risk_level") == "high" for c in checks.values()):
        return None, []
    ev = _event_dicts(event_rows(session, company))
    return registry_delay(ev, checks, company_df(session, company), as_of_of(session, company),
                          get_settings().registry_delay_days)


def scenario(session: Session, company: Company, sc: dict[str, Any], horizon: int = 30) -> dict[str, Any]:
    state, notes = get_state(session, company, horizon)
    adj, adj_notes = _registry_adjustment(session, company)
    notes = notes + adj_notes + _cushion_note(session, company)
    sc = copy.deepcopy(sc)
    if sc["type"] == "client_delay":
        # id события из /events → его контрагент: ядро сдвинет все поступления клиента (регулярные и счета)
        target = str(sc["params"]["counterparty_or_event_id"]).strip()
        row = session.scalar(select(EventRow).where(EventRow.company_id == company.id, EventRow.id == target))
        sc["params"]["counterparty_or_event_id"] = (row.counterparty or target) if row is not None else target
    # поправка по реестрам входит и в базу, и в сценарий: база совпадает с GET /forecast
    res = get_core().scenario(state, sc, horizon, base_adjustment=adj)
    extra = notes + _api_notes(session, company)
    return {"base": _finish(res["base"], company, extra), "scenario": _finish(res["scenario"], company, extra),
            "delta": {"first_gap_date": res.get("delta", {}).get("first_gap_date"),
                      "max_shortfall": res.get("delta", {}).get("max_shortfall")}}


def categories(session: Session, company: Company, limit: int | None = None) -> dict[str, Any]:
    from .categories import summarize

    core = get_core()
    df = company_df(session, company)
    if core.name == "stub":
        mock = json.loads((get_settings().mock_dir / "categories.json").read_text(encoding="utf-8"))
        return mock
    return summarize(core.categorize(df), limit)


def add_transactions(session: Session, company: Company, rows_in: list[dict[str, Any]]) -> dict[str, Any]:
    """Новые операции → update_forecast без полного пересчёта; статусы событий — в хранилище."""
    if not rows_in:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Передайте хотя бы одну операцию")
    if len(rows_in) > 5000:
        raise HTTPException(413, "Слишком много операций за один раз (максимум 5000)")
    rows, errors = [], []
    for i, r in enumerate(rows_in, 1):
        norm, why = normalize_row(r)
        if norm is None:
            errors.append(f"строка {i}: {why}")
        else:
            rows.append(norm)
    if not rows:
        raise HTTPException(422, "Ни одна операция не принята: " + "; ".join(errors[:5]))
    state, notes = get_state(session, company)
    core = get_core()
    core_rows = [{**r, "date": r["date"].isoformat()} for r in rows]
    with _locks[company.id]:
        new_state, res = core.update(state, core_rows)
    company.tx_version += 1
    batch = (session.scalar(select(func.max(Transaction.batch)).where(Transaction.company_id == company.id)) or 0) + 1
    _store_rows(session, company.id, rows, batch)
    # статусы событий, которые ядро сопоставило с новыми операциями
    st_events = {e.get("id"): e.get("status") for e in core.state_events(new_state)}
    for r in event_rows(session, company):
        s = st_events.get(r.id)
        if s in ("paid", "overdue") and not r.status_locked and r.status != s:
            r.status = s
    session.commit()
    _reconcile(session, company, company_df(session, company), as_of_of(session, company))
    status_by_id = {r.id: r.status for r in event_rows(session, company)}
    for e in core.state_events(new_state):          # те же статусы — в состояние ядра (без пересборки)
        if e.get("id") in status_by_id:
            e["status"] = status_by_id[e["id"]]
    ev = _event_dicts(event_rows(session, company))
    key = _key(company, ev, checks_map(session, company), _state_horizon(30), cushion_of(session, company)[0])
    _cache[company.id] = (key, new_state)
    _save_state(session, company, key, new_state)
    extra = [f"Принято операций: {len(rows)}" + (f", с ошибками: {len(errors)} ({'; '.join(errors[:3])})" if errors else "")]
    # прогноз по обновлённому состоянию (статусы событий сверены, поправка реестров — как в /forecast)
    adj, adj_notes = _registry_adjustment(session, company)
    upd_warn = list(res.get("warnings") or [])
    res = core.forecast(new_state, 30, adj)
    res["warnings"] = list(dict.fromkeys(list(res.get("warnings") or []) + upd_warn))
    return _finish(res, company, notes + adj_notes + extra + _api_notes(session, company))


# --------------------------------------------------------------------------- интеграции
def sync(session: Session, company: Company, name: str) -> dict[str, Any]:
    integs = all_integrations(get_settings().registry_delay_days)
    if name not in integs or name == "manual":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Источник «{name}» не найден. Есть: bank, 1c, tax_calendar, registry, contracts, invoices")
    integ = integs[name]
    ctx = context(session, company)
    events = integ.fetch(ctx)
    added, updated = upsert_events(session, company, events, name)
    msg = integ.message(ctx, events)
    if name == "registry":
        checks = integ.check(ctx)
        session.execute(delete(CounterpartyCheck).where(CounterpartyCheck.company_id == company.id))
        for c in checks:
            session.add(CounterpartyCheck(company_id=company.id, inn=c.inn, name=c.name, risk_level=c.risk_level,
                                          delay_days=c.delay_days, reasons=c.reasons, details=c.details))
        session.commit()
        _annotate_risky(session, company)
    _reconcile(session, company, ctx.df, ctx.as_of)
    session.add(IntegrationRun(company_id=company.id, name=name, events_added=added, events_updated=updated, message=msg))
    session.commit()
    invalidate(company.id)
    return {"name": name, "status": "ok", "events_added": added, "synced_at": now_iso(), "events_updated": updated,
            "message": msg}


def _annotate_risky(session: Session, company: Company) -> None:
    """Пометить в note события-поступления от проблемных контрагентов (видно пользователю)."""
    checks = checks_map(session, company)
    for r in event_rows(session, company):
        chk = None
        if r.counterparty_inn and r.counterparty_inn in checks:
            chk = checks[r.counterparty_inn]
        elif r.counterparty:
            chk = next((c for c in checks.values() if c["name"].strip().lower() == r.counterparty.strip().lower()), None)
        marker = "⚠ Риск задержки оплаты"
        base_note = (r.note or "").split(f" · {marker}")[0]
        if chk and chk["risk_level"] in ("high", "medium") and r.direction == "in":
            r.note = f"{base_note} · {marker} ({'высокий' if chk['risk_level'] == 'high' else 'средний'}): " + "; ".join(chk["reasons"][:3])
        elif r.note and marker in r.note:
            r.note = base_note
    session.commit()


def integrations_status(session: Session, company: Company) -> list[dict[str, Any]]:
    integs = all_integrations(get_settings().registry_delay_days)
    ctx = context(session, company)
    out = []
    for name, integ in integs.items():
        last = session.scalar(select(IntegrationRun).where(IntegrationRun.company_id == company.id, IntegrationRun.name == name)
                              .order_by(IntegrationRun.synced_at.desc()))
        has_doc = name in ("tax_calendar", "bank", "registry", "manual") or ctx.document(name) is not None
        n = session.scalar(select(func.count()).select_from(EventRow).where(EventRow.company_id == company.id, EventRow.origin == name))
        out.append({"name": name, "title": integ.title, "source": integ.source, "description": integ.description,
                    "available": has_doc, "events": int(n or 0),
                    "last_sync": last.synced_at.isoformat() if last else None, "message": last.message if last else ""})
    return out


def save_document(session: Session, company: Company, kind: str, filename: str, content: bytes) -> None:
    doc = session.scalar(select(Document).where(Document.company_id == company.id, Document.kind == kind))
    if doc is None:
        session.add(Document(company_id=company.id, kind=kind, filename=filename, content=content))
    else:
        doc.filename, doc.content, doc.uploaded_at = filename, content, utcnow()
    session.commit()


def counterparty_checks(session: Session, company: Company) -> list[dict[str, Any]]:
    return [{"inn": c.inn, "name": c.name, "risk_level": c.risk_level, "delay_days": c.delay_days, "reasons": c.reasons,
             "checked_at": c.checked_at.isoformat()}
            for c in session.scalars(select(CounterpartyCheck).where(CounterpartyCheck.company_id == company.id)
                                     .order_by(CounterpartyCheck.risk_level))]


# --------------------------------------------------------------------------- план-факт
def _views(rows: list[EventRow]) -> list[pf.EventView]:
    return [pf.EventView(id=r.id, type=r.type, direction=r.direction, amount=r.amount, date=r.date, source=r.source,
                         status=r.status, counterparty=r.counterparty or "", counterparty_inn=r.counterparty_inn or "",
                         note=r.note or "", status_locked=r.status_locked, paid_date=r.paid_date, paid_amount=r.paid_amount)
            for r in rows]


def _reconcile(session: Session, company: Company, df: pd.DataFrame, as_of: date | None) -> tuple[list[EventRow], list[pf.Match]]:
    """Сверить события с выпиской. Возвращает события, ставшие просроченными, и все совпадения."""
    if as_of is None:
        return [], []
    rows = event_rows(session, company)
    matches = pf.reconcile(_views(rows), df, as_of)
    by_id = {r.id: r for r in rows}
    newly_overdue = []
    for m in matches:
        r = by_id.get(m.event_id)
        if r is None or r.status_locked:
            continue
        if m.paid_amount is not None:
            r.paid_date, r.paid_amount = m.paid_date, m.paid_amount
        if r.status != m.status:
            if m.status == "overdue":
                newly_overdue.append(r)
            r.status = m.status
    session.commit()
    return newly_overdue, matches


def plan_fact(session: Session, company: Company, weeks: int = 8, period: str = "week") -> list[dict[str, Any]]:
    df = company_df(session, company)
    as_of = as_of_of(session, company)
    if as_of is None:
        return []
    row = session.get(ForecastStateRow, company.id)
    before = (row.result or {}).get("risks") if row is not None and row.result else None
    newly_overdue, matches = _reconcile(session, company, df, as_of)
    if newly_overdue:
        # просрочка → пересчёт прогноза и повторная проверка риска
        invalidate(company.id)
        after = forecast(session, company, 30).get("risks", [])
        names = ", ".join(f"{r.counterparty or r.type} {rub(r.amount)} ({day_month(r.date)})" for r in newly_overdue[:3])
        top = max(after, key=lambda x: x["probability"]) if after else None
        txt = f"Просрочено: {names}. Прогноз пересчитан"
        if top:
            was = max((b["probability"] for b in before or []), default=None)
            txt += f": риск разрыва {day_month(top['date'])} — {top['probability']:.0%}" + (f" (было {was:.0%})" if was is not None else "")
        else:
            txt += ": разрыва в ближайшие 30 дней не ожидается"
        add_note(session, company, txt + ".")
    recurring = []
    try:
        state, _ = get_state(session, company, 30)
        recurring = get_core().forecast(state, 30).get("recurring", []) if get_core().name != "stub" else []
    except Exception:  # noqa: BLE001 — план-факт работает и без регулярных платежей
        log.warning("recurring unavailable for plan-fact")
    rows = event_rows(session, company)
    return pf.build(df, _views(rows), recurring, as_of, matches, weeks=weeks, period=period)
