"""Сборка прогноза: состояние, план платежей, Monte Carlo (п.4 задания).

Остаток не прогнозируется напрямую. Прогнозируются потоки, остаток собирается:

``остаток(t) = остаток(сегодня) + Σ детерминированные платежи + Σ остаточные потоки``

* **детерминированная часть** — регулярные платежи (:mod:`recurring`), налоговые
  всплески (:mod:`taxes`) и переданные события (договоры, счета, налоги, ручной ввод);
* **стохастическая часть** — остальные поступления и списания (:mod:`flows`),
  модель выбирается по ошибкам прошлых прогнозов на этих же данных;
* **неопределённость** — Monte Carlo: шум сумм, вероятность задержки входящих
  платежей (клиент платит позже), ошибки остаточной модели из прошлых прогнозов.

Пополнения «собственными средствами» и новые займы/кредиты в прогноз не
закладываются: прогноз отвечает на вопрос «что будет, если ничего не делать».
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from .categorize import Categorizer, fit_categorizer
from .flows import MODEL_FACTORIES, error_paths
from .io import load_statement, to_daily
from .log import get_logger
from .recurring import RecurringPattern, find_patterns
from .schema import EVENT_SOURCES, EVENT_STATUSES, EVENT_TYPES, INTERVAL_SCALE
from .taxes import TaxModel, fit_tax_model

log = get_logger(__name__)

EVENT_CATEGORY = {"tax": "taxes", "payroll": "payroll", "loan": "loans", "manual": "other"}
MOVABLE_CATEGORIES = ("suppliers", "rent", "utilities", "other")
#: Поступления, которые владелец делает «по необходимости» — не закладываются в прогноз.
RESCUE_INFLOW_CATEGORIES = ("transfers", "loans")


def _stable_int(s: str) -> int:
    return int(hashlib.sha1(s.encode("utf-8")).hexdigest()[:8], 16)


# --------------------------------------------------------------------------- plan
@dataclass
class PlannedItem:
    """Один ожидаемый платёж в горизонте прогноза."""

    id: str
    day: int                      # смещение от первого дня прогноза
    direction: str
    amount: float
    category: str
    kind: str                     # recurring | tax | event
    name: str
    counterparty: str = ""
    source: str = "bank"
    cv: float = 0.1
    prob_occur: float = 1.0
    delay_prob: float = 0.0
    delay_max: int = 21
    movable: bool = False
    ref: str = ""                 # ключ паттерна или id события
    amount_mult: float = 1.0      # модификаторы сценариев
    day_shift: int = 0

    @property
    def expected_amount(self) -> float:
        return self.amount * self.amount_mult


@dataclass
class Plan:
    """Всё, что нужно для симуляции одного варианта (база или сценарий)."""

    start: date
    horizon: int
    start_balance: float
    items: list[PlannedItem]
    res_in: np.ndarray
    res_out: np.ndarray
    in_mult: np.ndarray
    out_mult: np.ndarray
    extra: np.ndarray             # детерминированные добавки (например, задержанная часть потока)
    warnings: list[str] = field(default_factory=list)

    def copy(self) -> "Plan":
        return Plan(self.start, self.horizon, self.start_balance, [replace(i) for i in self.items],
                    self.res_in.copy(), self.res_out.copy(), self.in_mult.copy(), self.out_mult.copy(),
                    self.extra.copy(), list(self.warnings))

    @property
    def dates(self) -> list[date]:
        return [self.start + timedelta(days=k) for k in range(self.horizon)]


# --------------------------------------------------------------------------- state
@dataclass
class ForecastState:
    """Состояние прогноза: всё, что нужно для быстрого пересчёта и инкрементального обновления."""

    company_id: str
    df: pd.DataFrame
    daily: pd.DataFrame
    as_of: date
    start_balance: float
    patterns: list[RecurringPattern]
    inactive: list[RecurringPattern]
    tax_model: TaxModel
    categorizer: Categorizer | None
    res_in: pd.Series
    res_out: pd.Series
    model_name: str
    raw_in: pd.Series
    raw_out: pd.Series
    models: dict[str, Any]
    err_in: np.ndarray
    err_out: np.ndarray
    err_scale: float
    events: list[dict[str, Any]]
    mode: str                                  # full | simplified | minimal
    warnings: list[str]
    settings: dict[str, Any]
    model_scores: dict[str, float] = field(default_factory=dict)
    fitted_as_of: date | None = None
    hist_min_balance: float = 0.0
    excluded_tax_from_residual: bool = False
    last_update: dict[str, Any] = field(default_factory=dict)


def normalize_events(events: list[dict[str, Any]] | None, start: date) -> tuple[list[dict[str, Any]], list[str]]:
    """Проверить и нормализовать события контракта. Плохие события пропускаются с предупреждением."""
    out, warns = [], []
    for i, e in enumerate(events or []):
        try:
            e = dict(e)
            etype = str(e.get("type") or "manual")
            if etype not in EVENT_TYPES:
                warns.append(f"Событие {e.get('id', i)}: неизвестный тип «{etype}», принят manual.")
                etype = "manual"
            direction = e.get("direction") or ("out" if etype in ("tax", "payroll", "loan") else None)
            if direction not in ("in", "out"):
                raise ValueError("direction")
            amount = abs(float(e.get("amount")))
            if not np.isfinite(amount) or amount <= 0:
                raise ValueError("amount")
            d = pd.to_datetime(e.get("date"), errors="coerce")
            if pd.isna(d):
                raise ValueError("date")
            status = str(e.get("status") or "expected")
            if status not in EVENT_STATUSES:
                status = "expected"
            source = str(e.get("source") or "manual")
            if source not in EVENT_SOURCES:
                source = "manual"
            eid = str(e.get("id") or f"ev{_stable_int(f'{etype}{direction}{amount}{d}') % 10**8}")
            out.append({**e, "id": eid, "type": etype, "direction": direction, "amount": amount,
                        "date": d.date().isoformat(), "status": status, "source": source,
                        "counterparty": str(e.get("counterparty") or ""), "note": str(e.get("note") or "")})
        except (TypeError, ValueError) as exc:
            warns.append(f"Событие {e.get('id', i) if isinstance(e, dict) else i} пропущено: некорректное поле {exc}.")
    return out, warns


def _residual_series(df: pd.DataFrame, daily: pd.DataFrame, exclude_ids: set[str],
                     exclude_tax: bool) -> tuple[pd.Series, pd.Series]:
    d = df[~df["tx_id"].isin(exclude_ids)]
    d = d[~((d["direction"] == "in") & d["category"].isin(RESCUE_INFLOW_CATEGORIES))]
    if exclude_tax:
        d = d[~((d["direction"] == "out") & (d["category"] == "taxes"))]
    idx = daily.index
    dd = pd.to_datetime(d["date"])
    r_in = d[d["direction"] == "in"].groupby(dd[d["direction"] == "in"])["amount"].sum().reindex(idx).fillna(0.0)
    r_out = d[d["direction"] == "out"].groupby(dd[d["direction"] == "out"])["amount"].sum().reindex(idx).fillna(0.0)
    return r_in.astype(float), r_out.astype(float)


def _winsorize(y: pd.Series) -> pd.Series:
    """Срезать разовые гигантские операции, чтобы они не раздували средний уровень."""
    if len(y) < 60 or (y > 0).sum() < 20:
        return y
    pos = y[y > 0]
    cap = float(np.quantile(pos, 0.995)) * 1.5
    return y.clip(upper=cap)


def _select_model(r_in: pd.Series, r_out: pd.Series, horizon: int, candidates: list[str], seed: int,
                  raw_in: pd.Series | None = None, raw_out: pd.Series | None = None
                  ) -> tuple[str, np.ndarray, np.ndarray, dict[str, float]]:
    """Выбрать модель остаточных потоков по ошибке накопленного остатка на прошлых прогнозах."""
    best = None
    scores: dict[str, float] = {}
    for name in candidates:
        e_in, _ = error_paths(r_in, name, horizon, seed=seed, y_true=raw_in)
        e_out, _ = error_paths(r_out, name, horizon, seed=seed, y_true=raw_out)
        if len(e_in) < 5:
            continue
        cum_err = np.cumsum(e_in - e_out, axis=1)
        score = float(np.mean(np.abs(cum_err)))
        scores[name] = round(score, 2)
        if best is None or score < best[0]:
            best = (score, name, e_in, e_out)
    if best is None:
        return candidates[0], np.zeros((0, horizon)), np.zeros((0, horizon)), scores
    return best[1], best[2], best[3], scores


def build_state(
    df: pd.DataFrame | str,
    events: list[dict[str, Any]] | None = None,
    horizon: int = 30,
    *,
    company_id: str | None = None,
    model: str = "auto",
    n_sims: int = 2000,
    seed: int = 42,
    threshold: float = 0.0,
    as_of: date | None = None,
    categorizer: Categorizer | None = None,
    interval_scale: float | None = None,
    comfort_balance: float | None = None,
) -> ForecastState:
    """Подготовить состояние прогноза (очистка, категории, паттерны, модели, ошибки).

    Args:
        df: выписка (сырой DataFrame, путь к CSV или результат :func:`load_statement`).
        events: ожидаемые события в формате контракта.
        horizon: горизонт (дней), минимум 30 рекомендуется.
        model: "auto" | "ets" | "gbm" | "naive" — модель остаточных потоков.
        threshold: порог «разрыва» (по умолчанию остаток < 0).
        comfort_balance: минимальный комфортный остаток владельца (подушка безопасности); по умолчанию —
            расходы примерно за 7 дней (средние списания за 90 дней без переводов между своими счетами).
        interval_scale: множитель ширины интервалов (по умолчанию калиброванный :data:`schema.INTERVAL_SCALE`).
        as_of: обрезать историю этой датой (для бэктеста).
    """
    t0 = time.time()
    horizon = int(max(1, min(int(horizon or 30), 365)))
    if isinstance(df, pd.DataFrame) and "signed_amount" in df.columns and "tx_id" in df.columns:
        tx = df.copy()
    else:
        tx = load_statement(df, company_id=company_id)
    warnings = list(tx.attrs.get("warnings", []))
    cid = str(company_id or tx.attrs.get("company_id") or "unknown")
    tx.attrs = {}
    if as_of is not None and len(tx):
        tx = tx[pd.to_datetime(tx["date"]).dt.date <= as_of].reset_index(drop=True)

    if not len(tx):
        today = as_of or date.today()
        empty_idx = pd.DatetimeIndex([], name="date")
        warnings.append("Нет операций — прогноз построен как «остаток не меняется».")
        ev, ew = normalize_events(events, today + timedelta(days=1))
        return ForecastState(cid, tx, to_daily(tx), today, 0.0, [], [], TaxModel(), None,
                             pd.Series(dtype=float, index=empty_idx), pd.Series(dtype=float, index=empty_idx),
                             "mean", pd.Series(dtype=float, index=empty_idx), pd.Series(dtype=float, index=empty_idx), {}, np.zeros((0, horizon)), np.zeros((0, horizon)), 2.0, ev, "minimal",
                             warnings + ew, {"horizon": horizon, "n_sims": n_sims, "seed": seed, "threshold": threshold,
                                             "comfort_balance": float(comfort_balance or 0.0),
                                             "comfort_source": "user" if comfort_balance is not None else "auto"})

    cz = categorizer or fit_categorizer(tx, seed=seed)
    tx = cz.transform(tx)
    daily = to_daily(tx)
    as_of_d = daily.index[-1].date()
    start_balance = float(daily["balance_reported"].iloc[-1]) if daily["balance_reported"].notna().any() \
        else float(daily["balance"].iloc[-1])
    hist_days = len(daily)

    if hist_days < 14 or len(tx) < 10:
        mode = "minimal"
        warnings.append(f"История всего {hist_days} дн.: прогноз очень приблизительный (средние потоки), уверенность низкая.")
    elif hist_days < 90:
        mode = "simplified"
        warnings.append(f"История короче 3 месяцев ({hist_days} дн.): упрощённая модель, уверенность низкая.")
    else:
        mode = "full"

    all_pats = find_patterns(tx, as_of_d, active_only=False) if mode != "minimal" else []
    patterns = [p for p in all_pats if p.is_active(as_of_d)]
    inactive = [p for p in all_pats if not p.is_active(as_of_d) and p.confidence >= 0.5] if mode == "full" else []
    for p in inactive:
        if p.direction == "in" and p.category == "revenue":
            warnings.append(f"Регулярные поступления «{p.name}» прекратились — в прогноз не включены.")
    tm = fit_tax_model(tx, as_of_d) if mode == "full" else TaxModel()
    has_tax_pattern = any(p.category == "taxes" for p in patterns)
    exclude_tax = has_tax_pattern or bool(tm.ratio_by_moy)

    ids = {t for p in patterns for t in p.tx_ids}
    r_in, r_out = _residual_series(tx, daily, ids, exclude_tax)
    r_in_w, r_out_w = _winsorize(r_in), _winsorize(r_out)

    err_h = max(horizon, 30)
    scores: dict[str, float] = {}
    if mode == "minimal":
        model_name, e_in, e_out, scale = "mean", np.zeros((0, err_h)), np.zeros((0, err_h)), 2.0
    else:
        if model == "auto":
            cands = ["ets", "gbm"] if (mode == "full" and hist_days >= 240) else ["ets"]
        else:
            cands = [model if model in MODEL_FACTORIES else "ets"]
        try:
            model_name, e_in, e_out, scores = _select_model(r_in_w, r_out_w, err_h, cands, seed, r_in, r_out)
        except Exception as exc:  # noqa: BLE001 — модель не должна ронять прогноз
            log.warning("model selection failed: %s", type(exc).__name__)
            model_name, e_in, e_out, scores = _select_model(r_in_w, r_out_w, err_h, ["ets"], seed, r_in, r_out)
            warnings.append("Сложная модель не обучилась на этих данных — использована сезонная.")
        scale = 1.0 if mode == "full" else 1.5
        if len(e_in) < 8:
            scale = max(scale, 1.5)
    models = {}
    if model_name in MODEL_FACTORIES:
        models = {"in": MODEL_FACTORIES[model_name](seed).fit(r_in_w), "out": MODEL_FACTORIES[model_name](seed).fit(r_out_w)}

    # Подушка безопасности: задал владелец или «расходы примерно за 7 дней»
    if comfort_balance is not None and np.isfinite(float(comfort_balance)) and float(comfort_balance) >= 0:
        comfort, comfort_src = float(comfort_balance), "user"
    else:
        recent_out = tx[(tx["direction"] == "out") & (tx["category"] != "transfers")
                        & (pd.to_datetime(tx["date"]) > pd.Timestamp(as_of_d) - pd.Timedelta(days=90))]
        span = min(90, hist_days)
        comfort, comfort_src = round(float(recent_out["amount"].sum()) / max(span, 1) * 7, -2), "auto"

    # Один клиент даёт большую часть выручки — риск концентрации
    rev = tx[(tx["direction"] == "in") & (tx["category"] == "revenue")]
    if len(rev) and mode != "minimal":
        last90 = rev[pd.to_datetime(rev["date"]) > pd.Timestamp(as_of_d) - pd.Timedelta(days=90)]
        if len(last90):
            key = np.where(last90["counterparty_inn"] != "", last90["counterparty_inn"], last90["counterparty_name"])
            share = last90.groupby(key)["amount"].sum().sort_values(ascending=False)
            top = share.iloc[0] / share.sum() if share.sum() > 0 else 0
            bank_like = str(last90.loc[key == share.index[0], "counterparty_name"].iloc[0]).lower()
            if top > 0.5 and "банк" not in bank_like:
                warnings.append(f"Один клиент даёт {top:.0%} выручки за 90 дней — задержка его оплаты сильно влияет на прогноз.")

    ev, ew = normalize_events(events, as_of_d + timedelta(days=1))
    warnings.extend(ew)
    known_cps = set(tx["counterparty_name"].str.lower()) | set(tx["counterparty_inn"])
    for e in ev:
        cp = e.get("counterparty", "")
        if cp and cp.lower() not in known_cps and e["direction"] == "in":
            e["_new_counterparty"] = True
    if any(e.get("_new_counterparty") for e in ev):
        warnings.append("Есть ожидаемые поступления от новых контрагентов без истории оплат — для них заложен повышенный риск задержки.")

    st = ForecastState(
        company_id=cid, df=tx, daily=daily, as_of=as_of_d, start_balance=start_balance, patterns=patterns,
        inactive=inactive, tax_model=tm, categorizer=cz, res_in=r_in_w, res_out=r_out_w, model_name=model_name,
        raw_in=r_in, raw_out=r_out,
        models=models, err_in=e_in, err_out=e_out, err_scale=scale, events=ev, mode=mode, warnings=warnings,
        settings={"horizon": horizon, "n_sims": int(n_sims), "seed": int(seed), "threshold": float(threshold),
                  "model": model, "interval_scale": float(INTERVAL_SCALE if interval_scale is None else interval_scale),
                  "comfort_balance": comfort, "comfort_source": comfort_src},
        model_scores=scores, fitted_as_of=as_of_d,
        hist_min_balance=float(daily["balance"].min()), excluded_tax_from_residual=exclude_tax,
    )
    log.info("state built: mode=%s model=%s patterns=%d days=%d secs=%.2f", mode, model_name, len(patterns),
             hist_days, time.time() - t0)
    return st


# --------------------------------------------------------------------------- plan building
def _residual_forecast(state: ForecastState, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    if state.mode == "minimal" or not state.models:
        n = max(len(state.res_in), 1)
        mi = float(state.res_in.sum() / n) if len(state.res_in) else 0.0
        mo = float(state.res_out.sum() / n) if len(state.res_out) else 0.0
        return np.full(horizon, mi), np.full(horizon, mo)
    return state.models["in"].forecast(state.res_in, horizon), state.models["out"].forecast(state.res_out, horizon)


def _event_matches_pattern(e: dict[str, Any], p: RecurringPattern) -> bool:
    if e["direction"] != p.direction:
        return False
    cat = EVENT_CATEGORY.get(e["type"]) or ("revenue" if e["direction"] == "in" else "suppliers")
    cp = (e.get("counterparty") or "").lower()
    same_cp = bool(cp) and (cp in p.counterparty.lower() or cp == p.counterparty_inn)
    return same_cp or (cat == p.category and p.category in ("taxes", "payroll", "loans", "rent"))


def build_plan(state: ForecastState, horizon: int | None = None) -> Plan:
    """Расписание детерминированных платежей + прогноз остаточных потоков на горизонт."""
    H = int(horizon or state.settings["horizon"])
    start = state.as_of + timedelta(days=1)
    end = start + timedelta(days=H - 1)
    items: list[PlannedItem] = []

    for p in state.patterns:
        for nom, exp in p.schedule(end):
            day = (exp - start).days
            if day < 0:
                # ожидаемый платёж уже должен был пройти, но его нет — считаем, что придёт/уйдёт сейчас
                day = 0
            if p.direction == "in":
                prob = 0.5 + 0.5 * p.confidence
                delay = float(np.clip(0.1 + p.late_share, 0.1, 0.6))
            else:
                prob, delay = 1.0, 0.0
            items.append(PlannedItem(
                id=f"rec:{p.key}:{nom.isoformat()}", day=day, direction=p.direction, amount=p.amount_forecast,
                category=p.category, kind="recurring", name=p.name, counterparty=p.counterparty, source="bank",
                cv=min(0.5, max(0.03, p.amount_cv)), prob_occur=prob, delay_prob=delay,
                movable=p.category in MOVABLE_CATEGORIES, ref=p.key))

    for t in state.tax_model.items(start, end):
        items.append(PlannedItem(
            id=f"tax:{t['date'].isoformat()}", day=(t["date"] - start).days, direction="out", amount=t["amount"],
            category="taxes", kind="tax", name=f"квартальный налоговый платёж ({state.tax_model.regime.get('label', '')})",
            source="bank", cv=t["cv"], ref="tax_model"))

    for e in state.events:
        if e["status"] == "paid":
            continue
        d = date.fromisoformat(e["date"])
        overdue = e["status"] == "overdue" or d < start
        if d > end:
            continue
        day = max(0, (d - start).days)
        cat = EVENT_CATEGORY.get(e["type"]) or ("revenue" if e["direction"] == "in" else "suppliers")
        if e["direction"] == "in":
            delay = 0.6 if overdue else (0.3 if e.get("_new_counterparty") else 0.15)
            prob = 0.85 if overdue else 0.97
        else:
            delay, prob = 0.0, 1.0
        # событие точнее регулярного паттерна: убираем совпадающее плановое вхождение
        win = 10 if e["type"] == "tax" else 7
        for it in list(items):
            if it.kind == "recurring":
                p = next((pp for pp in state.patterns if pp.key == it.ref), None)
                if p and _event_matches_pattern(e, p) and abs(it.day - day) <= win and 0.5 <= it.amount / e["amount"] <= 2.0:
                    items.remove(it)
                    break
        if e["type"] == "tax":
            items = [it for it in items if not (it.kind == "tax" and abs(it.day - day) <= win)]
        items.append(PlannedItem(
            id=f"ev:{e['id']}", day=day, direction=e["direction"], amount=e["amount"], category=cat, kind="event",
            name=e.get("note") or {"tax": "налог", "payroll": "зарплата", "loan": "платёж по кредиту",
                                   "contract": "оплата по договору", "invoice": "оплата счёта",
                                   "manual": "платёж"}.get(e["type"], "платёж"),
            counterparty=e.get("counterparty", ""), source=e["source"], cv=0.02, prob_occur=prob,
            delay_prob=delay, movable=e["direction"] == "out" and e["type"] in ("contract", "invoice", "manual"),
            ref=e["id"]))

    r_in, r_out = _residual_forecast(state, H)
    return Plan(start=start, horizon=H, start_balance=state.start_balance, items=items, res_in=r_in, res_out=r_out,
                in_mult=np.ones(H), out_mult=np.ones(H), extra=np.zeros(H))


# --------------------------------------------------------------------------- simulation
@dataclass
class SimResult:
    balances: np.ndarray        # (n_sims, H)
    det_in: np.ndarray          # средние детерминированные потоки по дням
    det_out: np.ndarray


def simulate(state: ForecastState, plan: Plan, n_sims: int | None = None, seed: int | None = None) -> SimResult:
    """Monte Carlo траекторий остатка. Случайность привязана к id платежей — у сценариев
    и базы одинаковые случайные числа (common random numbers), поэтому разница честная."""
    n = int(n_sims or state.settings["n_sims"])
    seed = int(state.settings["seed"] if seed is None else seed)
    H = plan.horizon
    flows = np.zeros((n, H))
    det_in, det_out = np.zeros(H), np.zeros(H)
    rows = np.arange(n)
    for it in plan.items:
        rng = np.random.default_rng([seed, _stable_int(it.id)])
        z = rng.standard_normal(n)
        u_occ = rng.random(n)
        u_del = rng.random(n)
        dd = rng.integers(3, max(4, it.delay_max + 1), n)
        jitter = rng.integers(-1, 2, n) if it.direction == "in" and it.kind == "recurring" else np.zeros(n, dtype=int)
        sigma = float(min(max(it.cv, 0.0), 0.6))
        amt = it.expected_amount * np.exp(sigma * z - 0.5 * sigma ** 2)
        occurs = u_occ < it.prob_occur
        delay = np.where(u_del < it.delay_prob, dd, 0)
        day = it.day + it.day_shift + delay + jitter
        day = np.maximum(day, 0)
        ok = occurs & (day < H)
        sign = 1.0 if it.direction == "in" else -1.0
        np.add.at(flows, (rows[ok], day[ok]), sign * amt[ok])
        d0 = it.day + it.day_shift
        if 0 <= d0 < H:
            (det_in if sign > 0 else det_out)[d0] += it.expected_amount * it.prob_occur

    rng0 = np.random.default_rng([seed, 0])
    e_in, e_out = state.err_in, state.err_out
    if len(e_in) >= 5 and e_in.shape[1] >= H:
        pick = rng0.integers(0, len(e_in), n)
        # калибровка ширины (k) растягивает только непрерывный шум модели потоков, а не дискретные
        # события (задержку клиента и т.п.) — поэтому сценарии всегда сдвигают риск в правильную сторону
        k = float(state.settings.get("interval_scale", INTERVAL_SCALE))
        scale = k * state.err_scale * np.exp(0.1 * rng0.standard_normal(n))[:, None]
        res_in = (plan.res_in[None, :] + scale * e_in[pick, :H]) * plan.in_mult[None, :]
        res_out = (plan.res_out[None, :] + scale * e_out[pick, :H]) * plan.out_mult[None, :]
    else:
        # мало истории для эмпирических ошибок — нормальный шум по дневной волатильности
        sd_in = float(state.res_in.std()) if len(state.res_in) > 1 else 0.0
        sd_out = float(state.res_out.std()) if len(state.res_out) > 1 else 0.0
        if not np.isfinite(sd_in):
            sd_in = 0.0
        if not np.isfinite(sd_out):
            sd_out = 0.0
        k = float(state.settings.get("interval_scale", INTERVAL_SCALE))
        res_in = (plan.res_in[None, :] + k * state.err_scale * sd_in * rng0.standard_normal((n, H))) * plan.in_mult[None, :]
        res_out = (plan.res_out[None, :] + k * state.err_scale * sd_out * rng0.standard_normal((n, H))) * plan.out_mult[None, :]
    total = flows + res_in - res_out + plan.extra[None, :]
    balances = plan.start_balance + np.cumsum(total, axis=1)
    return SimResult(balances=balances, det_in=det_in, det_out=det_out)


# --------------------------------------------------------------------------- result
def _daily_points(plan: Plan, sim: SimResult) -> list[dict[str, Any]]:
    from .schema import INTERVAL_HIGH_Q, INTERVAL_LOW_Q

    q = np.quantile(sim.balances, [INTERVAL_LOW_Q, 0.5, INTERVAL_HIGH_Q], axis=0)
    ev_by_day: dict[int, list[str]] = {}
    for it in plan.items:
        if it.kind == "event" and it.ref != "scenario":
            ev_by_day.setdefault(it.day + it.day_shift, []).append(it.ref)
    out = []
    for k, d in enumerate(plan.dates):
        p = {"date": d.isoformat(), "balance_p50": round(float(q[1, k]), 2), "balance_low": round(float(q[0, k]), 2),
             "balance_high": round(float(q[2, k]), 2)}
        if k in ev_by_day:
            p["events"] = ev_by_day[k]  # необязательное поле контракта: id событий на дату
        out.append(p)
    return out


def make_result(state: ForecastState, plan: Plan, sim: SimResult, extra_warnings: list[str] | None = None) -> dict[str, Any]:
    """Собрать ForecastResult (dict строго по контракту + warnings)."""
    from .risk import find_risks

    risks = find_risks(state, plan, sim)
    sources = ["bank"] + sorted({e["source"] for e in state.events if e["source"] != "bank"})
    warnings = list(dict.fromkeys(state.warnings + plan.warnings + (extra_warnings or [])))
    return {
        "company_id": state.company_id,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "horizon_days": plan.horizon,
        "as_of": state.as_of.isoformat(),
        "current_balance": round(float(state.start_balance), 2),
        "comfort_balance": round(float(state.settings.get("comfort_balance") or 0.0), 2),
        "daily": _daily_points(plan, sim),
        "risks": risks,
        "recurring": [p.to_contract(state.as_of) for p in state.patterns],
        "sources_used": sources,
        "warnings": warnings,
    }


def forecast_from_state(state: ForecastState, horizon: int | None = None, scenario: dict[str, Any] | None = None
                        ) -> dict[str, Any]:
    """Прогноз по готовому состоянию (опционально — со сценарием)."""
    from .scenarios import apply_scenario

    H = int(horizon or state.settings["horizon"])
    ensure_error_horizon(state, H)
    plan = build_plan(state, H)
    if scenario:
        plan = apply_scenario(state, plan, scenario)
    sim = simulate(state, plan)
    return make_result(state, plan, sim)


def ensure_error_horizon(state: ForecastState, horizon: int) -> None:
    """Досчитать эмпирические ошибки, если запрошен горизонт длиннее посчитанного."""
    if state.mode == "minimal" or state.model_name not in MODEL_FACTORIES:
        return
    if len(state.err_in) and state.err_in.shape[1] >= horizon:
        return
    seed = state.settings["seed"]
    state.err_in, _ = error_paths(state.res_in, state.model_name, horizon, seed=seed, y_true=state.raw_in)
    state.err_out, _ = error_paths(state.res_out, state.model_name, horizon, seed=seed, y_true=state.raw_out)
    if len(state.err_in) < 8:
        state.err_scale = max(state.err_scale, 1.5)
