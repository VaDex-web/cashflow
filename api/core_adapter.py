"""Подключение ядра: заглушка (ответы из docs/mock) или настоящий ``cashflow_core``.

Переключатель — ``USE_STUB_CORE=true/false``. Сигнатуры и JSON одинаковые (docs/contract.md, п. 3),
поэтому остальной код API не знает, какое ядро работает.
"""
from __future__ import annotations

import copy
import io
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import get_settings

log = logging.getLogger("api.core")


class StubCore:
    """Заглушка ядра: та же сигнатура, ответы — примеры из docs/mock/*.json."""

    name = "stub"
    version = "mock"

    def __init__(self, mock_dir: Path):
        self.mock_dir = mock_dir

    def _mock(self, name: str) -> Any:
        return json.loads((self.mock_dir / name).read_text(encoding="utf-8"))

    def load_statement(self, src: Any) -> pd.DataFrame:
        from .statements import parse_statement_bytes

        raw = src.getvalue() if isinstance(src, io.BytesIO) else src
        rows, warnings = parse_statement_bytes(raw)
        df = pd.DataFrame(rows)
        df.attrs["warnings"] = warnings
        return df

    def build(self, df: pd.DataFrame, events: list[dict[str, Any]], horizon: int, company_id: str,
              base_state: Any = None, comfort_balance: float | None = None) -> dict[str, Any]:
        return {"company_id": company_id, "events": copy.deepcopy(events), "horizon": horizon, "n_rows": len(df)}

    def forecast(self, state: dict[str, Any], horizon: int, scenario: dict[str, Any] | None = None) -> dict[str, Any]:
        r = self._mock("forecast.json")
        r["company_id"] = state["company_id"]
        r["generated_at"] = _now()
        r["daily"] = r["daily"][:horizon]
        r["horizon_days"] = len(r["daily"])
        ids = {e["id"] for e in state["events"]}
        r["sources_used"] = sorted({"bank", *(e["source"] for e in state["events"])}) if ids else r["sources_used"]
        return r

    def scenario(self, state: dict[str, Any], scenario: dict[str, Any], horizon: int,
                 base_adjustment: dict[str, Any] | None = None) -> dict[str, Any]:
        r = self._mock("scenario_result.json")
        for k in ("base", "scenario"):
            r[k]["company_id"] = state["company_id"]
            r[k]["generated_at"] = _now()
        return r

    def update(self, state: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        state = dict(state, n_rows=state.get("n_rows", 0) + len(rows))
        return state, self.forecast(state, state.get("horizon", 30))

    def categorize(self, df: pd.DataFrame) -> pd.DataFrame:
        from .categories import categorize_simple

        return categorize_simple(df)

    def tax_regime(self, df: pd.DataFrame) -> dict[str, Any]:
        return {"regime": "unknown", "label": "не удалось определить", "confidence": 0.0, "evidence": []}

    def state_events(self, state: Any) -> list[dict[str, Any]]:
        return state.get("events", []) if isinstance(state, dict) else []


class RealCore:
    """Настоящее ядро ``cashflow_core`` (core/). Вызывает только функции из контракта и README ядра."""

    name = "cashflow_core"

    def __init__(self, module: Any):
        self.m = module
        self.version = getattr(module, "__version__", "?")
        self.has_state = hasattr(module, "build_state") and hasattr(module, "forecast_from_state")

    def load_statement(self, src: Any) -> pd.DataFrame:
        return self.m.load_statement(src)

    def build(self, df: pd.DataFrame, events: list[dict[str, Any]], horizon: int, company_id: str,
              base_state: Any = None, comfort_balance: float | None = None) -> Any:
        """Порог разрыва — 0 ₽; ``comfort_balance`` — комфортный минимум владельца (второй вид риска, контракт)."""
        s = get_settings()
        if not self.has_state:
            return {"df": df, "events": events, "horizon": horizon, "company_id": company_id}
        kw: dict[str, Any] = {"company_id": company_id, "n_sims": s.n_sims, "threshold": 0.0}
        if comfort_balance is not None:
            kw["comfort_balance"] = float(comfort_balance)
        src = df
        if base_state is not None and getattr(base_state, "categorizer", None) is not None:
            # события поменялись, операции те же: переиспользуем обученный категоризатор (в 2 раза быстрее)
            kw["categorizer"] = base_state.categorizer
            src = base_state.df
        return self.m.build_state(src, events, max(horizon, 30), **kw)

    def _run(self, state: Any, horizon: int, scenarios: list[dict[str, Any]]) -> tuple[dict[str, Any], Any, Any]:
        """Прогноз по состоянию с цепочкой сценариев и полем ``risks[].kind`` (контракт).

        Те же шаги, что ``forecast_from_state`` ядра, но сценариев может быть несколько (поправка по реестрам +
        сценарий пользователя), а риски берутся с видом: ``gap`` (ниже 0 ₽) или ``below_comfort``.
        """
        from cashflow_core.engine import build_plan, ensure_error_horizon, make_result, simulate  # noqa: PLC0415
        from cashflow_core.risk import find_risks  # noqa: PLC0415
        from cashflow_core.scenarios import apply_scenario  # noqa: PLC0415

        ensure_error_horizon(state, horizon)
        plan = build_plan(state, horizon)
        for sc in scenarios:
            plan = apply_scenario(state, plan, sc)
        sim = simulate(state, plan)
        res = make_result(state, plan, sim)
        res["risks"] = find_risks(state, plan, sim, with_kind=True)
        return res, plan, sim

    def forecast(self, state: Any, horizon: int, scenario: dict[str, Any] | None = None) -> dict[str, Any]:
        if isinstance(state, dict):
            return self.m.forecast(state["df"], state["events"], horizon, scenario=scenario, company_id=state["company_id"])
        return self._run(state, horizon, [scenario] if scenario else [])[0]

    def scenario(self, state: Any, scenario: dict[str, Any], horizon: int,
                 base_adjustment: dict[str, Any] | None = None) -> dict[str, Any]:
        """``base_adjustment`` — поправка основного прогноза (задержка проблемного контрагента по реестрам):
        входит и в базу, и в сценарий, чтобы база совпадала с ``GET /forecast``."""
        if isinstance(state, dict):
            return self.m.run_scenarios(state["df"], state["events"], scenario, company_id=state["company_id"],
                                        horizon=horizon)
        from cashflow_core.risk import gap_summary  # noqa: PLC0415

        base_chain = [base_adjustment] if base_adjustment else []
        scn_chain = [a for a in base_chain if not _same_delay(a, scenario)] + [scenario]
        base, bp, bs = self._run(state, horizon, base_chain)
        scn, sp, ss = self._run(state, horizon, scn_chain)
        gb, gs = gap_summary(bp, bs, 0.0), gap_summary(sp, ss, 0.0)
        return {"base": base, "scenario": scn, "delta": {
            "first_gap_date": gs["first_gap_date"], "max_shortfall": gs["max_shortfall"],
            "first_gap_date_base": gb["first_gap_date"], "max_shortfall_base": gb["max_shortfall"]}}

    def update(self, state: Any, rows: list[dict[str, Any]]) -> tuple[Any, dict[str, Any]]:
        if isinstance(state, dict):
            df = pd.concat([state["df"], self.m.load_statement(pd.DataFrame(rows))], ignore_index=True)
            state = dict(state, df=df)
            return state, self.forecast(state, state["horizon"])
        return self.m.update_forecast(state, rows)

    def categorize(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.m.categorize(df)

    def tax_regime(self, df: pd.DataFrame) -> dict[str, Any]:
        try:
            return self.m.estimate_tax_regime(self.m.categorize(df))
        except Exception as exc:  # noqa: BLE001
            log.warning("tax regime estimation failed: %s", type(exc).__name__)
            return {"regime": "unknown", "label": "не удалось определить", "confidence": 0.0, "evidence": []}

    def state_events(self, state: Any) -> list[dict[str, Any]]:
        if isinstance(state, dict):
            return state.get("events", [])
        return getattr(state, "events", None) or []


def _same_delay(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Пользователь сам задаёт задержку того же клиента — поправку по реестрам не складываем с ней."""
    if a.get("type") != "client_delay" or b.get("type") != "client_delay":
        return False
    ta = str(a["params"].get("counterparty_or_event_id", "")).strip().lower()
    tb = str(b["params"].get("counterparty_or_event_id", "")).strip().lower()
    return bool(ta) and (ta == tb or ta in tb or tb in ta)


_backend: StubCore | RealCore | None = None


def get_core() -> StubCore | RealCore:
    """Ядро по настройке USE_STUB_CORE. Если настоящее не импортируется — заглушка и предупреждение в логе."""
    global _backend
    if _backend is not None:
        return _backend
    s = get_settings()
    if s.use_stub_core:
        _backend = StubCore(s.mock_dir)
        return _backend
    if s.core_path.exists() and str(s.core_path) not in sys.path:
        sys.path.insert(0, str(s.core_path))
    try:
        import cashflow_core  # noqa: PLC0415

        _backend = RealCore(cashflow_core)
    except ImportError as exc:
        log.warning("cashflow_core недоступен (%s) — включена заглушка ядра", type(exc).__name__)
        _backend = StubCore(s.mock_dir)
    return _backend


def reset_core() -> None:
    global _backend
    _backend = None


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- события для ядра
def events_for_core(events: list[dict[str, Any]], checks: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """События по контракту для ядра. У поступлений от проблемных контрагентов (открытые реестры)
    добавлены поля ``risk`` и ``delay_probability`` — ядро может учитывать их напрямую."""
    out = []
    for e in events:
        ce = {k: e.get(k) for k in ("id", "type", "direction", "amount", "date", "source", "status", "counterparty", "note")}
        ce = {k: v for k, v in ce.items() if v is not None}
        chk = _find_check(e, checks)
        if chk and e.get("direction") == "in" and e.get("status") != "paid":
            ce["risk"] = chk["risk_level"]
            ce["delay_probability"] = 0.8 if chk["risk_level"] == "high" else 0.4
        out.append(ce)
    return out


def registry_delay(events: list[dict[str, Any]], checks: dict[str, dict[str, Any]], df: Any, as_of: date | None,
                   delay_days: int) -> tuple[dict[str, Any] | None, list[str]]:
    """Поправка прогноза на проблемного контрагента: сценарий ``client_delay`` (контракт, п. 2).

    Ядро сдвигает все ожидаемые поступления контрагента — и регулярные, и события — на ``delay_days``
    (округление до недель), поэтому двойного учёта нет. Если таких контрагентов несколько — берётся тот,
    от кого ждём больше денег (по событиям и выручке за 90 дней).
    """
    from .textfmt import rub

    risky = [c for c in checks.values() if c.get("risk_level") == "high"]
    if not risky or delay_days <= 0:
        return None, []
    weight: dict[str, float] = {}
    for c in risky:
        w = sum(float(e["amount"]) for e in events if e.get("direction") == "in" and e.get("status") != "paid"
                and _find_check(e, {c.get("inn") or c["name"]: c}) is not None)
        if df is not None and len(df) and as_of is not None:
            recent = df[(df["direction"] == "in") & (pd.to_datetime(df["date"]).dt.date > as_of - timedelta(days=90))]
            m = (recent["counterparty_inn"].astype(str) == str(c.get("inn") or "-")) | \
                (recent["counterparty_name"].astype(str).str.lower() == str(c.get("name", "")).lower())
            w += float(recent.loc[m, "amount"].sum()) / 3
        weight[c.get("inn") or c["name"]] = w
    key = max(weight, key=lambda k: weight[k])
    if weight[key] <= 0:
        return None, []
    c = next(x for x in risky if (x.get("inn") or x["name"]) == key)
    weeks = int(min(4, max(1, round(max(c.get("delay_days") or delay_days, 7) / 7))))
    why = "; ".join(c.get("reasons", [])[:3])
    note = (f"Учтён риск задержки оплаты от {c['name']}: по открытым реестрам — {why}. В прогнозе его поступления "
            f"(около {rub(weight[key])}) сдвинуты на {weeks} нед.")
    return {"type": "client_delay", "params": {"counterparty_or_event_id": c["name"], "weeks": weeks}}, [note]


def _find_check(e: dict[str, Any], checks: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    inn = str(e.get("counterparty_inn") or "")
    if inn and inn in checks:
        c = checks[inn]
    else:
        name = str(e.get("counterparty") or "").strip().lower()
        c = next((v for v in checks.values() if name and v.get("name", "").strip().lower() == name), None)
    if c and c.get("risk_level") in ("high", "medium"):
        return c
    return None
