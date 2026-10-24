from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from . import services as svc
from .config import get_settings
from .core_adapter import get_core
from .db import get_session
from .integrations import parse_text
from .schemas import (CategoriesResponse, CompanyCreated, CompanyInfo, CompanySettings, CompanySettingsIn, Event,
                      EventCreate, EventParseRequest, EventParseResult, EventUpdate, ForecastResult, Health, IntegrationName,
                      LoginRequest, LoginResponse, Me, MeUpdate, PlanFactRow, Recurring, Risk, Scenario, ScenarioResult,
                      SyncResponse)
from .security import authenticate, create_token, current_user
from .statements import StatementError

router = APIRouter(prefix="/api")
EXCLUDE_NONE: dict[str, Any] = {"response_model_exclude_none": True}


async def read_upload(file: UploadFile, request: Request) -> bytes:
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


@router.post("/auth/demo", response_model=LoginResponse, tags=["служебные"],
             summary="Демо-вход в один клик: гость со своей копией демо-компании → JWT")
def demo_login(session: Session = Depends(get_session)) -> dict[str, Any]:
    if not get_settings().demo_company:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Демо-вход выключен")
    from .demo import create_guest

    return {"access_token": create_token(create_guest(session)), "token_type": "bearer"}


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
            summary="Моя компания (один пользователь = одна компания); demo=true — плюс компании датасета и демо")
def companies(demo: bool = Query(False, description="скрытый демо-режим: показать компании из датасета"),
              user: str = Depends(current_user), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return svc.list_companies(session, user, demo)


@router.get("/me", response_model=Me, tags=["компании"], summary="Кто вошёл и какая у него компания")
def get_me(user: str = Depends(current_user), session: Session = Depends(get_session)) -> dict[str, Any]:
    return svc.me(session, user)


@router.put("/me", response_model=Me, tags=["компании"], summary="Демо-режим: выбрать компанию из датасета как свою")
def put_me(body: MeUpdate, user: str = Depends(current_user), session: Session = Depends(get_session)) -> dict[str, Any]:
    return svc.set_my_company(session, user, body.company_id)


@router.get("/companies/{cid}/settings", response_model=CompanySettings, tags=["компании"],
            summary="Настройки владельца: комфортный минимум на счёте, налоговый режим")
def get_settings_(cid: str, user: str = Depends(current_user), session: Session = Depends(get_session)) -> dict[str, Any]:
    return svc.company_settings(session, svc.get_company(session, cid, user))


@router.put("/companies/{cid}/settings", response_model=CompanySettings, tags=["компании"],
            summary="Изменить комфортный минимум (null — по умолчанию: расходы за 7 дней) и налоговый режим")
def put_settings(cid: str, body: CompanySettingsIn, user: str = Depends(current_user),
                 session: Session = Depends(get_session)) -> dict[str, Any]:
    return svc.update_settings(session, svc.get_company(session, cid, user, write=True), body.model_dump(exclude_unset=True))


@router.post("/predict", tags=["проверка"], summary="Прогноз по файлу без входа: остаток по дням и риски для каждой компании",
             description="Для тестов и контрольного датасета. Вход — CSV в формате датасета организаторов (одна или "
                         "несколько компаний). Для каждой компании прогноз строится от её последней даты, без данных из "
                         "будущего и без источников, seed фиксирован. Ответ `format=json` — {forecast: [{company_id, date, "
                         "balance_forecast, balance_low, balance_high}], companies: [{company_id, as_of, risks: [{date, "
                         "shortfall_amount, probability, severity}], warnings}]}; `format=csv` — только таблица прогноза. "
                         "То же из командной строки: `python -m api.predict <csv|папка> --horizon 30 --out predictions.csv`. "
                         "Ничего не сохраняется.")
async def predict(request: Request, file: UploadFile = File(...), horizon: int = Query(30, ge=1, le=365),
                  format: Literal["json", "csv"] = "json") -> Any:
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import PlainTextResponse

    from . import predict as pr

    if not get_settings().public_predict:
        raise HTTPException(403, "Прогноз без входа отключён на этом сервере")
    raw = await read_upload(file, request)
    try:
        companies = {cid: df for cid, df in _split_companies(pr.read_csv_bytes(raw, file.filename or "файл")).items()}
    except pr.PredictError as exc:
        raise HTTPException(400, str(exc)) from None
    rows, meta = await run_in_threadpool(pr.run, companies, horizon, 1, get_settings().n_sims)
    if format == "csv":
        return PlainTextResponse(pr.to_csv(rows), media_type="text/csv; charset=utf-8")
    return {"forecast": rows, **meta}


def _split_companies(df: Any) -> dict[str, Any]:
    return {str(cid): part.reset_index(drop=True) for cid, part in df.groupby(df["company_id"].str.strip(), sort=True)}


@router.get("/metrics", tags=["как это работает"], summary="Качество прогноза: бэктест ядра (core/reports/metrics.json)")
def metrics(user: str = Depends(current_user)) -> Any:
    import json

    p = get_settings().core_path / "reports" / "metrics.json"
    if not p.exists():
        raise HTTPException(404, "Отчёт о качестве прогноза ещё не построен")
    return json.loads(p.read_text(encoding="utf-8"))


@router.get("/metrics/sources", tags=["как это работает"], summary="Как источники данных улучшают прогноз (api/reports)")
def metrics_sources(user: str = Depends(current_user)) -> Any:
    import json
    from pathlib import Path

    p = Path(__file__).resolve().parent / "reports" / "sources_effect.json"
    if not p.exists():
        raise HTTPException(404, "Отчёт о вкладе источников ещё не построен")
    from .reports.sources_effect import summary

    return summary(json.loads(p.read_text(encoding="utf-8")))


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
    return svc.add_transactions(session, svc.get_company(session, cid, user, write=True), rows)


@router.get("/companies/{cid}/plan-fact", response_model=list[PlanFactRow], tags=["план-факт"],
            summary="План и факт по неделям, просрочки и отклонения; при просрочке — пересчёт прогноза")
def plan_fact(cid: str, weeks: int = Query(8, ge=1, le=26), period: Literal["week", "day"] = "week",
              user: str = Depends(current_user), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return svc.plan_fact(session, svc.get_company(session, cid, user), weeks, period)


@router.get("/companies/{cid}/events", response_model=list[Event], tags=["события"], **EXCLUDE_NONE,
            summary="Ожидаемые события из всех источников")
def list_events(cid: str, user: str = Depends(current_user), session: Session = Depends(get_session)) -> list[Event]:
    return [svc.to_event(r) for r in svc.event_rows(session, svc.get_company(session, cid, user))]


@router.post("/companies/{cid}/events", response_model=Event, status_code=200, tags=["события"], **EXCLUDE_NONE,
             summary="Добавить событие вручную («клиент обещал 300 000 ₽ 20-го»)")
def add_event(cid: str, body: EventCreate, user: str = Depends(current_user), session: Session = Depends(get_session)) -> Event:
    return svc.create_event(session, svc.get_company(session, cid, user, write=True), body)


@router.post("/companies/{cid}/events/parse", response_model=EventParseResult, tags=["события"], **EXCLUDE_NONE,
             summary="Разобрать фразу в событие (save=true — сразу сохранить)")
def parse_event(cid: str, body: EventParseRequest, save: bool = False, user: str = Depends(current_user),
                session: Session = Depends(get_session)) -> dict[str, Any]:
    company = svc.get_company(session, cid, user, write=save)
    today = svc.as_of_of(session, company) or date.today()
    try:
        ev, understood = parse_text(body.text, today)
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
    return svc.update_event(session, svc.get_company(session, cid, user, write=True), event_id, body)


@router.put("/companies/{cid}/events/{event_id}", response_model=Event, tags=["события"], **EXCLUDE_NONE)
def put_event(cid: str, event_id: str, body: EventCreate, user: str = Depends(current_user),
              session: Session = Depends(get_session)) -> Event:
    return svc.update_event(session, svc.get_company(session, cid, user, write=True), event_id, EventUpdate(**body.model_dump()))


@router.delete("/companies/{cid}/events/{event_id}", status_code=204, tags=["события"])
def remove_event(cid: str, event_id: str, user: str = Depends(current_user), session: Session = Depends(get_session)) -> None:
    svc.delete_event(session, svc.get_company(session, cid, user, write=True), event_id)


@router.post("/companies/{cid}/integrations/{name}/sync", response_model=SyncResponse, tags=["источники"], **EXCLUDE_NONE,
             summary="Синхронизировать источник: bank | 1c | tax_calendar | registry | contracts | invoices")
def sync(cid: str, name: IntegrationName, user: str = Depends(current_user), session: Session = Depends(get_session)) -> dict[str, Any]:
    return svc.sync(session, svc.get_company(session, cid, user, write=True), name)


@router.post("/companies/{cid}/integrations/{name}/upload", response_model=SyncResponse, tags=["источники"], **EXCLUDE_NONE,
             summary="Загрузить файл источника (выгрузка 1С, договоры, счета, bank.json, registry.json) и синхронизировать")
async def upload_source(cid: str, name: Literal["1c", "contracts", "invoices", "bank", "registry"], request: Request,
                        file: UploadFile = File(...), user: str = Depends(current_user),
                        session: Session = Depends(get_session)) -> dict[str, Any]:
    company = svc.get_company(session, cid, user, write=True)
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
