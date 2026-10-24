"""Демо-вход в один клик, изоляция гостей, лимит запросов и логи без чувствительных данных."""
from __future__ import annotations

import logging

from .conftest import ROOT, SYN, login, make_client, my_company


def _demo(client) -> dict[str, str]:
    r = client.post("/api/auth/demo")
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_demo_guests_get_own_copies(stub):
    a, b = _demo(stub), _demo(stub)
    ca = stub.get("/api/me", headers=a).json()["company_id"]
    cb = stub.get("/api/me", headers=b).json()["company_id"]
    assert ca and cb and ca != cb and ca.startswith("s02-")
    assert stub.get(f"/api/companies/{ca}/forecast", headers=a).status_code == 200
    # событие гостя A не видно гостю B, а чужая копия закрыта
    ev = {"type": "manual", "direction": "out", "amount": 1000, "date": "2026-11-01"}
    assert stub.post(f"/api/companies/{ca}/events", headers=a, json=ev).status_code == 200
    assert all(e["amount"] != 1000 for e in stub.get(f"/api/companies/{cb}/events", headers=b).json())
    assert stub.get(f"/api/companies/{ca}/events", headers=b).status_code == 403
    # шаблон демо снаружи недоступен
    assert stub.get("/api/companies/demo-template/forecast", headers=a).status_code == 403


def test_shared_companies_are_read_only(stub):
    """Общие компании (датасет, демо) можно смотреть, но нельзя менять — ни гостю, ни пользователю demo."""
    g, d = _demo(stub), login(stub)
    ev = {"type": "manual", "direction": "out", "amount": 9_000_000, "date": "2026-11-01"}
    for h in (g, d):
        assert stub.get("/api/companies/S01/forecast", headers=h).status_code == 200      # читать можно
        assert stub.post("/api/companies/S01/events/parse", headers=h, json={"text": "клиент обещал 300 000 ₽ 20-го"}).status_code == 200
        r = stub.post("/api/companies/S01/events", headers=h, json=ev)
        assert r.status_code == 403 and "только в вашей копии" in r.json()["detail"]
        assert stub.post("/api/companies/S01/events/parse?save=true", headers=h,
                         json={"text": "клиент обещал 300 000 ₽ 20-го"}).status_code == 403
        assert stub.patch("/api/companies/S01/events/x", headers=h, json={"date": "2026-11-25"}).status_code == 403
        assert stub.put("/api/companies/S01/events/x", headers=h, json=ev).status_code == 403
        assert stub.delete("/api/companies/S01/events/x", headers=h).status_code == 403
        assert stub.put("/api/companies/S01/settings", headers=h, json={"safety_cushion": 1}).status_code == 403
        assert stub.post("/api/companies/S01/transactions", headers=h,
                         json=[{"date": "2026-10-26", "amount": 5, "direction": "out"}]).status_code == 403
        assert stub.post("/api/companies/S01/integrations/tax_calendar/sync", headers=h).status_code == 403
        assert stub.post("/api/companies/S01/integrations/invoices/upload", headers=h,
                         files={"file": ("i.csv", b"number;amount\n1;5\n", "text/csv")}).status_code == 403
    assert stub.get("/api/companies/S01/events", headers=g).json() == []


def test_choosing_shared_company_gives_private_copy(stub):
    """PUT /me на общую компанию — личная копия: события одного гостя не видят другой гость и demo."""
    a, b, d = _demo(stub), _demo(stub), login(stub)
    ca = stub.put("/api/me", headers=a, json={"company_id": "S01"}).json()["company_id"]
    cb = stub.put("/api/me", headers=b, json={"company_id": "S01"}).json()["company_id"]
    assert ca.startswith("s01-") and cb.startswith("s01-") and ca != cb
    ev = {"type": "manual", "direction": "out", "amount": 9_000_000, "date": "2026-11-01", "note": "мусор гостя"}
    r = stub.post(f"/api/companies/{ca}/events", headers=a, json=ev)
    assert r.status_code == 200
    assert stub.delete(f"/api/companies/{ca}/events/{r.json()['id']}", headers=b).status_code == 403   # чужая копия
    seen = [stub.get(f"/api/companies/{cid}/events", headers=h).json() for cid, h in
            ((cb, b), ("S01", d), (my_company(stub, d), d))]
    assert all(e["amount"] != 9_000_000 for evs in seen for e in evs)
    assert stub.get(f"/api/companies/{ca}/events", headers=d).status_code == 403
    # у demo своя копия S02, а не общая S02
    assert my_company(stub, d).startswith("s02-")


def test_demo_copy_has_sources_and_ready_forecast(real):
    h = _demo(real)
    cid = real.get("/api/me", headers=h).json()["company_id"]
    f = real.get(f"/api/companies/{cid}/forecast", headers=h).json()
    assert f["company_id"] == cid
    assert set(f["sources_used"]) >= {"bank", "1c", "tax_calendar", "open_registry"}
    gaps = [r for r in f["risks"] if r.get("kind") == "gap"]
    assert gaps and "2026-11-01" <= gaps[0]["date"] <= "2026-11-09"


def test_rate_limit(tmp_path):
    with make_client(tmp_path, stub=True, rate_limit_per_min=5, rate_limit_heavy_per_min=2) as c:
        codes = [c.post("/api/auth/login", json={"username": "demo", "password": "x"}).status_code for _ in range(3)]
        assert codes[:2] == [401, 401] and codes[2] == 429
        assert "Слишком много запросов" in c.post("/api/auth/login", json={"username": "demo", "password": "x"}).json()["detail"]
        assert c.get("/api/health").status_code == 200          # health не ограничен


def test_logs_have_no_sensitive_data(tmp_path, caplog):
    """Полный сценарий (вход, загрузка выписки, прогноз, события, источники) — в логах нет ИНН, названий,
    назначений, сумм и токенов."""
    raw = (ROOT / "data" / "synthetic" / "statements" / "S05.csv").read_bytes()
    text = raw.decode("utf-8-sig")
    lines = [ln.split(";") for ln in text.splitlines()[1:40]]
    header = text.splitlines()[0].split(";")
    inns = {r[header.index("counterparty_inn")] for r in lines if r[header.index("counterparty_inn")]}
    names = {r[header.index("counterparty_name")] for r in lines if r[header.index("counterparty_name")]}
    purposes = {r[header.index("payment_purpose")] for r in lines if len(r[header.index("payment_purpose")]) > 12}
    amounts = {r[header.index("amount")] for r in lines if float(r[header.index("amount")]) >= 10000}
    with caplog.at_level(logging.DEBUG), make_client(tmp_path, stub=True) as c:
        tok = c.post("/api/auth/login", json={"username": "demo", "password": "demo"}).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        cid = c.post("/api/companies", headers=h, files={"file": ("S05.csv", raw, "text/csv")}).json()["company_id"]
        c.get(f"/api/companies/{cid}/forecast", headers=h)
        c.post(f"/api/companies/{cid}/events", headers=h,
               json={"type": "manual", "direction": "in", "amount": 777777, "date": "2026-11-01", "counterparty": "ООО «Тайна»"})
        for name in ("tax_calendar", "registry"):
            c.post(f"/api/companies/{cid}/integrations/{name}/sync", headers=h)
        c.get(f"/api/companies/{cid}/events?token={tok}", headers=h)
        logging.getLogger("api.test").info("debug %s %s", tok, "Bearer " + tok)
    logged = caplog.text
    assert "GET /api/companies/" in logged                       # access-лог есть
    assert tok not in logged and tok[:20] not in logged
    for secret in [*inns, *names, *purposes, *amounts, "777777", "Тайна"]:
        assert secret not in logged, secret
