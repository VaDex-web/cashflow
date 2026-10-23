"""Сквозной сценарий на настоящем ядре cashflow_core (пропускается, если ядро не найдено).

Демо-компания S02: по одной выписке риск 5 ноября низкий; с источниками (налоговый календарь, 1С,
банк, реестры) — высокий, как и было «на самом деле» (data/synthetic/future/S02.csv).
"""
from __future__ import annotations

from api.schemas import ForecastResult, ScenarioResult

from .conftest import login


def _risk_on(f: dict, day_from: str, day_to: str) -> float:
    return max((r["probability"] for r in f["risks"] if day_from <= r["date"] <= day_to), default=0.0)


def test_s02_sources_reveal_gap(real):
    h = login(real)
    base = real.get("/api/companies/S02/forecast", headers=h).json()
    ForecastResult.model_validate(base)
    assert base["as_of"] == "2026-10-23" and len(base["daily"]) == 30
    assert _risk_on(base, "2026-11-01", "2026-11-10") < 0.5
    for name in ("tax_calendar", "1c", "bank", "registry"):
        assert real.post(f"/api/companies/S02/integrations/{name}/sync", headers=h).status_code == 200
    full = real.get("/api/companies/S02/forecast", headers=h).json()
    assert _risk_on(full, "2026-11-02", "2026-11-09") >= 0.6
    assert set(full["sources_used"]) >= {"bank", "1c", "tax_calendar", "open_registry"}
    assert any("ДонТрансЛогистика" in w for w in full["warnings"])

    sc = real.post("/api/companies/S02/scenarios/run", headers=h,
                   json={"type": "unplanned_expense", "params": {"amount": 1500000, "date": "2026-10-29"}})
    assert sc.status_code == 200
    ScenarioResult.model_validate(sc.json())
    assert sc.json()["delta"]["first_gap_date"] is not None

    pf = real.get("/api/companies/S02/plan-fact", headers=h).json()
    texts = [d["text"] for row in pf for d in row["deviations"]]
    assert any("ДонТрансЛогистика" in t and "не оплатил" in t for t in texts)

    rows = [{"date": "2026-10-26", "amount": 57900, "direction": "out", "counterparty_name": "ПАО «Банк»",
             "counterparty_inn": "0068275202", "purpose": "Погашение кредита и процентов по кредитному договору №КД-2025/0311",
             "balance_eod": 2463414.4}]
    upd = real.post("/api/companies/S02/transactions", headers=h, json=rows)
    assert upd.status_code == 200
    assert upd.json()["as_of"] == "2026-10-26"
    loans = [e for e in real.get("/api/companies/S02/events", headers=h).json() if e["type"] == "loan"]
    assert any(e["date"] == "2026-10-26" and e["status"] == "paid" for e in loans)


def test_dataset_style_upload_real(real):
    h = login(real)
    from .conftest import SYN

    raw = (SYN / "statements" / "S05.csv").read_bytes()
    r = real.post("/api/companies", headers=h, files={"file": ("S05.csv", raw, "text/csv")})
    assert r.status_code == 200, r.text
    cid = r.json()["company_id"]
    cats = real.get(f"/api/companies/{cid}/categories", headers=h).json()
    shares_in = sum(x["share"] for x in cats["summary"] if x["direction"] == "in")
    assert abs(shares_in - 1) < 0.01 and cats["transactions"][0]["date"] >= cats["transactions"][-1]["date"]
