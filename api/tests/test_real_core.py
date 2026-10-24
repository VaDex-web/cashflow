from __future__ import annotations

from api.schemas import ForecastResult, ScenarioResult

from .conftest import login, my_company


def _risk_on(f: dict, day_from: str, day_to: str) -> float:
    return max((r["probability"] for r in f["risks"] if day_from <= r["date"] <= day_to), default=0.0)


def test_s02_sources_reveal_gap(real):
    h = login(real)
    cid = my_company(real, h)
    assert real.put(f"/api/companies/{cid}/settings", headers=h, json={"safety_cushion": 0}).status_code == 200
    base = real.get(f"/api/companies/{cid}/forecast", headers=h).json()
    ForecastResult.model_validate(base)
    assert base["as_of"] == "2026-10-23" and len(base["daily"]) == 30
    assert _risk_on(base, "2026-11-01", "2026-11-10") < 0.5
    for name in ("tax_calendar", "1c", "bank", "registry"):
        assert real.post(f"/api/companies/{cid}/integrations/{name}/sync", headers=h).status_code == 200
    full = real.get(f"/api/companies/{cid}/forecast", headers=h).json()
    assert _risk_on(full, "2026-11-02", "2026-11-09") >= 0.6
    assert set(full["sources_used"]) >= {"bank", "1c", "tax_calendar", "open_registry"}
    assert any("ДонТрансЛогистика" in w for w in full["warnings"])

    sc = real.post(f"/api/companies/{cid}/scenarios/run", headers=h,
                   json={"type": "unplanned_expense", "params": {"amount": 1500000, "date": "2026-10-29"}})
    assert sc.status_code == 200
    ScenarioResult.model_validate(sc.json())
    assert sc.json()["delta"]["first_gap_date"] is not None

    pf = real.get(f"/api/companies/{cid}/plan-fact", headers=h).json()
    texts = [d["text"] for row in pf for d in row["deviations"]]
    assert any("ДонТрансЛогистика" in t and "не оплатил" in t for t in texts)

    rows = [{"date": "2026-10-26", "amount": 57900, "direction": "out", "counterparty_name": "ПАО «Банк»",
             "counterparty_inn": "0068275202", "purpose": "Погашение кредита и процентов по кредитному договору №КД-2025/0311",
             "balance_eod": 2463414.4}]
    upd = real.post(f"/api/companies/{cid}/transactions", headers=h, json=rows)
    assert upd.status_code == 200
    assert upd.json()["as_of"] == "2026-10-26"
    loans = [e for e in real.get(f"/api/companies/{cid}/events", headers=h).json() if e["type"] == "loan"]
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


def test_safety_cushion_raises_risk_earlier(real):
    h = login(real)
    cid = real.put("/api/me", headers=h, json={"company_id": "S01"}).json()["company_id"]
    zero = real.put(f"/api/companies/{cid}/settings", headers=h, json={"safety_cushion": 0}).json()
    assert zero["safety_cushion"] == 0
    f0 = real.get(f"/api/companies/{cid}/forecast", headers=h).json()
    st = real.put(f"/api/companies/{cid}/settings", headers=h, json={"safety_cushion": None}).json()
    assert st["safety_cushion_default"] > 0
    f1 = real.get(f"/api/companies/{cid}/forecast", headers=h).json()
    p0 = max((r["probability"] for r in f0["risks"]), default=0)
    p1 = max((r["probability"] for r in f1["risks"]), default=0)
    assert p1 >= p0


def test_risk_kinds_and_scenario_base_matches_forecast(real):
    h = login(real)
    cid = my_company(real, h)
    assert real.put(f"/api/companies/{cid}/settings", headers=h, json={"safety_cushion": None}).status_code == 200
    for name in ("tax_calendar", "1c", "bank", "registry"):
        assert real.post(f"/api/companies/{cid}/integrations/{name}/sync", headers=h).status_code == 200
    f = real.get(f"/api/companies/{cid}/forecast", headers=h).json()
    assert f["comfort_balance"] > 0
    assert f["risks"] and all(r["kind"] in ("gap", "below_comfort") for r in f["risks"])
    for r in f["risks"]:
        if r["kind"] == "gap":
            day = next(d for d in f["daily"] if d["date"] == r["date"])
            assert day["balance_low"] < 0
    sc = real.post(f"/api/companies/{cid}/scenarios/run", headers=h,
                   json={"type": "revenue_drop", "params": {"percent": 20}}).json()
    ScenarioResult.model_validate(sc)
    assert [d["balance_p50"] for d in sc["base"]["daily"]] == [d["balance_p50"] for d in f["daily"]]
