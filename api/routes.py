"""Эндпоинты /api по docs/contract.md (п. 4) + расширения (CRUD событий, загрузка файлов источников, разбор фразы)."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from . import services as svc
from .config import get_settings
from .core_adapter import get_core
from .db import get_session
from .integrations import parse_text
from .schemas import (CategoriesResponse, CompanyCreated, CompanyInfo, Event, EventCreate, EventParseRequest,
                      EventParseResult, EventUpdate, ForecastResult, Health, IntegrationName, LoginRequest, LoginResponse,
                      PlanFactRow, Recurring, Risk, Scenario, ScenarioResult, SyncResponse)
from .security import authenticate, current_user
from .statements import StatementError

router = APIRouter(prefix="/api")
EXCLUDE_NONE: dict[str, Any] = {"response_model_exclude_none": True}


async def read_upload(file: UploadFile, request: Request) -> bytes:
    """Прочитать файл с ограничением размера (413 с понятным текстом)."""
    limit = get_settings().max_upload_bytes
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > limit + 1024 * 64:
        raise HTTPException(413,
                            f"Файл больше {get_settings().max_upload_mb:.0f} МБ. Выгрузите выписку за меньший период.")
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(413,
                                f"Файл больше {get_settings().max_upload_mb:.0f} МБ. Выгрузите выписку за меньший период.")
    return bytes(buf)


# --------------------------------------------------------------------------- служебные
@router.get("/health", response_model=Health, tags=["служебные"], summary="Проверка работы сервиса")
def health() -> dict[str, Any]:
    core = get_core()
    return {"status": "ok", "core": f"{core.name} {core.version}"}


@router.post("/auth/login", response_model=LoginResponse, tags=["служебные"], summary="Вход: логин и пароль → JWT")
def login(body: LoginRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    token = authenticate(session, body.username, body.password)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    return {"access_token": token, "token_type": "bearer"}


# --------------------------------------------------------------------------- компании
@router.post("/companies", response_model=CompanyCreated, tags=["компании"], **EXCLUDE_NONE,
             summary="Загрузить выписку (CSV) — создаётся компания")
async def upload_company(request: Request, file: UploadFile = File(..., description="CSV-выписка"),
                         company: str | None = Query(None, description="id компании, если в файле несколько (all_operations.csv)"),
                         user: str = Depends(current_user), session: Session = Depends(get_session)) -> dict[str, Any]:
    name = file.filename or ""
    if name and not name.lower().endswith((".csv", ".txt")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Файл «{name}» не похож на CSV. Выгрузите выписку из интернет-банка в формате CSV.")
    raw = await read_upload(file, request)
    try:
        c, n, warnings = svc.create_company(session, raw, name, user, company)
    except StatementError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return {"company_id": c.id, "rows": n, "warnings": warnings or None}


@router.get("/companies", response_model=list[CompanyInfo], tags=["компании"],
            summary="Компании из датасета и демо-данных + загруженные пользователем")
def companies(user: str = Depends(current_user), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return svc.list_companies(session, user)


# --------------------------------------------------------------------------- прогноз
@router.get("/companies/{cid}/forecast", response_model=ForecastResult, tags=["прогноз"], **EXCLUDE_NONE,
            summary="Прогноз остатка по дням, риски разрывов, регулярные платежи")
def get_forecast(cid: str, horizon: int = Query(30, ge=7, le=365), user: str = Depends(current_user),
                 session: Session = Depends(get_session)) -> dict[str, Any]:
    return svc.forecast(session, svc.get_company(session, cid, user), horizon)


@router.get("/companies/{cid}/alerts", response_model=list[Risk], tags=["прогноз"], summary="Предупреждения о разрывах")
def alerts(cid: str, user: str = Depends(current_user), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return svc.forecast(session, svc.get_company(session, cid, user), 30)["risks"]


@router.get("/companies/{cid}/recurring", response_model=list[Recurring], tags=["прогноз"], summary="Регулярные платежи")
def recurring(cid: str, user: str = Depends(current_user), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return svc.forecast(session, svc.get_company(session, cid, user), 30)["recurring"]


@router.get("/companies/{cid}/categories", response_model=CategoriesResponse, tags=["прогноз"],
            summary="Операции по категориям и сводка")
def categories(cid: str, limit: int | None = Query(None, ge=1, le=100_000, description="сколько последних операций вернуть"),
               user: str = Depends(current_user), session: Session = Depends(get_session)) -> dict[str, Any]:
    return svc.categories(session, svc.get_company(session, cid, user), limit)


@router.post("/companies/{cid}/scenarios/run", response_model=ScenarioResult, tags=["прогноз"], **EXCLUDE_NONE,
             summary="Сценарий «что если»: базовый и негативный прогноз")
def run_scenario(cid: str, body: Scenario, user: str = Depends(current_user),
                 session: Session = Depends(get_session)) -> dict[str, Any]:
    return svc.scenario(session, svc.get_company(session, cid, user), body.model_dump())


@router.post("/companies/{cid}/transactions", response_model=ForecastResult, tags=["прогноз"], **EXCLUDE_NONE,
             summary="Добавить новые операции — прогноз обновляется без полного пересчёта (update_forecast)")
def add_transactions(cid: str, rows: list[dict[str, Any]] = Body(..., examples=[[{
        "date": "2026-10-26", "amount": 2322000, "direction": "in", "counterparty_name": "АО «ДонТрансЛогистика»",
        "counterparty_inn": "", "purpose": "Оплата по счету №205", "balance_eod": 4843314.4}]]),
        user: str = Depends(current_user), session: Session = Depends(get_session)) -> dict[str, Any]:
    return svc.add_transactions(session, svc.get_company(session, cid, user), rows)


@router.get("/companies/{cid}/plan-fact", response_model=list[PlanFactRow], tags=["план-факт"],
            summary="План и факт по неделям, просрочки и отклонения; при просрочке — пересчёт прогноза")
def plan_fact(cid: str, weeks: int = Query(8, ge=1, le=26), period: Literal["week", "day"] = "week",
              user: str = Depends(current_user), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return svc.plan_fact(session, svc.get_company(session, cid, user), weeks, period)


# --------------------------------------------------------------------------- события
@router.get("/companies/{cid}/events", response_model=list[Event], tags=["события"], **EXCLUDE_NONE,
            summary="Ожидаемые события из всех источников")
def list_events(cid: str, user: str = Depends(current_user), session: Session = Depends(get_session)) -> list[Event]:
    return [svc.to_event(r) for r in svc.event_rows(session, svc.get_company(session, cid, user))]


@router.post("/companies/{cid}/events", response_model=Event, status_code=200, tags=["события"], **EXCLUDE_NONE,
             summary="Добавить событие вручную («клиент обещал 300 000 ₽ 20-го»)")
def add_event(cid: str, body: EventCreate, user: str = Depends(current_user), session: Session = Depends(get_session)) -> Event:
    return svc.create_event(session, svc.get_company(session, cid, user), body)


@router.post("/companies/{cid}/events/parse", response_model=EventParseResult, tags=["события"], **EXCLUDE_NONE,
             summary="Разобрать фразу в событие (save=true — сразу сохранить)")
def parse_event(cid: str, body: EventParseRequest, save: bool = False, user: str = Depends(current_user),
                session: Session = Depends(get_session)) -> dict[str, Any]:
    company = svc.get_company(session, cid, user)
    today = svc.as_of_of(session, company)
    from datetime import date as _date

    try:
        ev, understood = parse_text(body.text, today or _date.today())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    out: dict[str, Any] = {"event": ev, "understood": understood}
    if save:
        out["saved"] = svc.create_event(session, company, ev)
    return out


@router.get("/companies/{cid}/events/{event_id}", response_model=Event, tags=["события"], **EXCLUDE_NONE)
def get_event(cid: str, event_id: str, user: str = Depends(current_user), session: Session = Depends(get_session)) -> Event:
    return svc.to_event(svc.get_event_row(session, svc.get_company(session, cid, user), event_id))


@router.patch("/companies/{cid}/events/{event_id}", response_model=Event, tags=["события"], **EXCLUDE_NONE,
              summary="Изменить событие (перенос даты, сумма, статус)")
def patch_event(cid: str, event_id: str, body: EventUpdate, user: str = Depends(current_user),
                session: Session = Depends(get_session)) -> Event:
    return svc.update_event(session, svc.get_company(session, cid, user), event_id, body)


@router.put("/companies/{cid}/events/{event_id}", response_model=Event, tags=["события"], **EXCLUDE_NONE)
def put_event(cid: str, event_id: str, body: EventCreate, user: str = Depends(current_user),
              session: Session = Depends(get_session)) -> Event:
    return svc.update_event(session, svc.get_company(session, cid, user), event_id, EventUpdate(**body.model_dump()))


@router.delete("/companies/{cid}/events/{event_id}", status_code=204, tags=["события"])
def remove_event(cid: str, event_id: str, user: str = Depends(current_user), session: Session = Depends(get_session)) -> None:
    svc.delete_event(session, svc.get_company(session, cid, user), event_id)


# --------------------------------------------------------------------------- интеграции
@router.post("/companies/{cid}/integrations/{name}/sync", response_model=SyncResponse, tags=["источники"], **EXCLUDE_NONE,
             summary="Синхронизировать источник: bank | 1c | tax_calendar | registry | contracts | invoices")
def sync(cid: str, name: IntegrationName, user: str = Depends(current_user), session: Session = Depends(get_session)) -> dict[str, Any]:
    return svc.sync(session, svc.get_company(session, cid, user), name)


@router.post("/companies/{cid}/integrations/{name}/upload", response_model=SyncResponse, tags=["источники"], **EXCLUDE_NONE,
             summary="Загрузить файл источника (выгрузка 1С, договоры, счета, bank.json, registry.json) и синхронизировать")
async def upload_source(cid: str, name: Literal["1c", "contracts", "invoices", "bank", "registry"], request: Request,
                        file: UploadFile = File(...), user: str = Depends(current_user),
                        session: Session = Depends(get_session)) -> dict[str, Any]:
    company = svc.get_company(session, cid, user)
    raw = await read_upload(file, request)
    if not raw.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Файл пустой.")
    import json

    from .integrations.contracts import parse_contracts
    from .integrations.invoices import parse_invoices

    try:
        if name == "contracts" and not parse_contracts(raw):
            raise ValueError("в файле не найдено ни одного договора")
        if name == "invoices" and not parse_invoices(raw):
            raise ValueError("в файле не найдено ни одного счёта с суммой и сроком оплаты")
        if name in ("1c", "bank", "registry"):
            json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError, KeyError, TypeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Не удалось прочитать файл «{file.filename}»: {exc}") from None
    svc.save_document(session, company, name, file.filename or name, raw)
    return svc.sync(session, company, name)


@router.get("/companies/{cid}/integrations", tags=["источники"], summary="Источники и их состояние")
def integrations(cid: str, user: str = Depends(current_user), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return svc.integrations_status(session, svc.get_company(session, cid, user))


@router.get("/companies/{cid}/counterparties/checks", tags=["источники"],
            summary="Результаты проверки контрагентов по открытым реестрам")
def counterparty_checks(cid: str, user: str = Depends(current_user), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return svc.counterparty_checks(session, svc.get_company(session, cid, user))
