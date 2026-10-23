"""Эндпоинты по контракту на ядре-заглушке: аутентификация, загрузка, схемы ответов, ошибки на русском."""
from __future__ import annotations

from api.schemas import CategoriesResponse, Event, ForecastResult, PlanFactRow, Recurring, Risk, ScenarioResult

from .conftest import SYN, login, make_client


def test_health_without_auth(stub):
    r = stub.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_login_and_errors(stub):
    assert stub.post("/api/auth/login", json={"username": "demo", "password": "wrong"}).status_code == 401
    r = stub.post("/api/auth/login", json={"username": "demo", "password": "wrong"})
    assert r.json()["detail"] == "Неверный логин или пароль"
    r = stub.get("/api/companies")
    assert r.status_code == 401 and "войти" in r.json()["detail"]
    r = stub.get("/api/companies", headers={"Authorization": "Bearer abc.def.ghi"})
    assert r.status_code == 401
    body = stub.post("/api/auth/login", json={"username": "demo", "password": "demo"}).json()
    assert body["token_type"] == "bearer" and body["access_token"].count(".") == 2


def test_one_user_one_company_and_demo_mode(stub, auth):
    r = stub.get("/api/companies", headers=auth)
    assert [c["company_id"] for c in r.json()] == ["S02"]          # после входа — только своя компания
    s02 = r.json()[0]
    assert set(s02) == {"company_id", "company_name", "legal_form", "industry", "first_operation_date",
                        "last_operation_date", "operations_count"}
    assert stub.get("/api/me", headers=auth).json() == {"username": "demo", "company_id": "S02",
                                                         "company_name": "ООО «Вектор Бизнес-Сервис»"}
    demo = [c["company_id"] for c in stub.get("/api/companies?demo=true", headers=auth).json()]
    assert demo[0] == "S02" and {"S01", "S05"} <= set(demo)         # скрытый демо-режим — весь список
    other = login(stub, "other")
    assert stub.get("/api/companies", headers=other).json() == []
    assert stub.put("/api/me", headers=other, json={"company_id": "S05"}).json()["company_id"] == "S05"
    assert [c["company_id"] for c in stub.get("/api/companies", headers=other).json()] == ["S05"]


def test_settings_safety_cushion(stub, auth):
    st = stub.get("/api/companies/S02/settings", headers=auth).json()
    assert st["safety_cushion_custom"] is False and st["safety_cushion"] == st["safety_cushion_default"] > 0
    assert st["tax_regime_estimated"]["regime"] == "osno"
    st = stub.put("/api/companies/S02/settings", headers=auth, json={"safety_cushion": 500000}).json()
    assert st["safety_cushion"] == 500000 and st["safety_cushion_custom"] is True
    f = stub.get("/api/companies/S02/forecast", headers=auth).json()
    assert any("комфортного минимума" in w and "500" in w for w in f["warnings"])
    st = stub.put("/api/companies/S02/settings", headers=auth, json={"safety_cushion": None}).json()
    assert st["safety_cushion_custom"] is False
    r = stub.put("/api/companies/S02/settings", headers=auth, json={"safety_cushion": -1})
    assert r.status_code == 422


def test_upload_and_isolation(stub, auth):
    raw = (SYN / "statements" / "S02.csv").read_bytes()
    r = stub.post("/api/companies", headers=auth, files={"file": ("S02.csv", raw, "text/csv")})
    assert r.status_code == 200, r.text
    cid = r.json()["company_id"]
    assert cid.startswith("s02-") and r.json()["rows"] > 500
    assert [c["company_id"] for c in stub.get("/api/companies", headers=auth).json()] == [cid]   # новая выписка — моя компания
    assert stub.get(f"/api/companies/{cid}/forecast", headers=auth).status_code == 200
    other = login(stub, "other")
    r = stub.get(f"/api/companies/{cid}/forecast", headers=other)
    assert r.status_code == 403 and r.json()["detail"] == "Нет доступа к этой компании"
    assert stub.get("/api/companies/nope/forecast", headers=auth).status_code == 404


def test_upload_errors_are_readable(stub, auth):
    def up(content: bytes, name: str = "f.csv"):
        return stub.post("/api/companies", headers=auth, files={"file": (name, content, "text/csv")})

    r = up(b"")
    assert r.status_code == 400 and r.json()["detail"] == "Файл пустой."
    r = up(b"PK\x03\x04....", "f.csv")
    assert r.status_code == 400 and "Excel" in r.json()["detail"]
    r = up("name;value\nА;1\n".encode())
    assert r.status_code == 400 and "колонками" in r.json()["detail"] or "Не нашли" in r.json()["detail"]
    r = up("дата;описание;остаток\n2026-01-01;x;5\n".encode())
    assert r.status_code == 400 and "сумма" in r.json()["detail"]
    r = up(b"x", "report.pdf")
    assert r.status_code == 400 and "CSV" in r.json()["detail"]


def test_upload_too_large(tmp_path):
    with make_client(tmp_path, stub=True, max_upload_mb=0.01) as c:
        h = login(c)
        big = b"date;amount;direction\n" + b"2026-01-01;100;in\n" * 2000
        r = c.post("/api/companies", headers=h, files={"file": ("big.csv", big, "text/csv")})
        assert r.status_code == 413 and "МБ" in r.json()["detail"]


def test_upload_multi_company_needs_param(stub, auth):
    text = ("company_id;operation_id;operation_date;amount;direction;counterparty_inn;counterparty_name;payment_purpose;balance_eod\n"
            "C1;1;2026-01-12;100.00;Поступление;001;А;x;100.00\nC2;1;2026-01-12;50.00;Списание;002;Б;y;-50.00\n")
    r = stub.post("/api/companies", headers=auth, files={"file": ("all.csv", text.encode("utf-8-sig"), "text/csv")})
    assert r.status_code == 400 and "нескольких компаний" in r.json()["detail"]
    r = stub.post("/api/companies?company=C2", headers=auth, files={"file": ("all.csv", text.encode("utf-8-sig"), "text/csv")})
    assert r.status_code == 200 and r.json()["rows"] == 1


def test_contract_shapes(stub, auth):
    cid = "S02"
    f = stub.get(f"/api/companies/{cid}/forecast?horizon=30", headers=auth)
    assert f.status_code == 200
    fr = ForecastResult.model_validate(f.json())
    assert fr.company_id == cid and len(fr.daily) == 30
    assert all("events" not in d or isinstance(d["events"], list) for d in f.json()["daily"])
    [Risk.model_validate(x) for x in stub.get(f"/api/companies/{cid}/alerts", headers=auth).json()]
    [Recurring.model_validate(x) for x in stub.get(f"/api/companies/{cid}/recurring", headers=auth).json()]
    CategoriesResponse.model_validate(stub.get(f"/api/companies/{cid}/categories", headers=auth).json())
    sc = stub.post(f"/api/companies/{cid}/scenarios/run", headers=auth, json={"type": "revenue_drop", "params": {"percent": 30}})
    assert sc.status_code == 200
    ScenarioResult.model_validate(sc.json())
    assert set(sc.json()["delta"]) == {"first_gap_date", "max_shortfall"}
    pf = stub.get(f"/api/companies/{cid}/plan-fact", headers=auth)
    assert pf.status_code == 200
    [PlanFactRow.model_validate(x) for x in pf.json()]


def test_scenario_validation_in_russian(stub, auth):
    r = stub.post("/api/companies/S02/scenarios/run", headers=auth, json={"type": "client_delay", "params": {"weeks": 3}})
    assert r.status_code == 422 and "клиента" in r.json()["detail"]
    r = stub.post("/api/companies/S02/scenarios/run", headers=auth, json={"type": "revenue_drop", "params": {"percent": 80}})
    assert r.status_code == 422 and "от 10 до 30%" in r.json()["detail"]
    r = stub.post("/api/companies/S02/scenarios/run", headers=auth, json={"type": "nope", "params": {}})
    assert r.status_code == 422 and r.json()["detail"].startswith("Проверьте данные")


def test_events_crud_and_parse(stub, auth):
    body = {"type": "manual", "direction": "in", "amount": 300000, "date": "2026-11-20", "source": "manual",
            "status": "expected", "counterparty": "ООО «Ромашка»", "note": "обещали"}
    r = stub.post("/api/companies/S02/events", headers=auth, json=body)
    assert r.status_code == 200, r.text
    ev = Event.model_validate(r.json())
    assert ev.id and ev.source == "manual"
    assert any(e["id"] == ev.id for e in stub.get("/api/companies/S02/events", headers=auth).json())
    r = stub.patch(f"/api/companies/S02/events/{ev.id}", headers=auth, json={"date": "2026-11-25"})
    assert r.json()["date"] == "2026-11-25"
    assert stub.delete(f"/api/companies/S02/events/{ev.id}", headers=auth).status_code == 204
    assert stub.get(f"/api/companies/S02/events/{ev.id}", headers=auth).status_code == 404
    bad = dict(body, amount=-5)
    r = stub.post("/api/companies/S02/events", headers=auth, json=bad)
    assert r.status_code == 422 and "сумма" in r.json()["detail"]
    r = stub.post("/api/companies/S02/events/parse?save=true", headers=auth,
                  json={"text": "клиент обещал заплатить 300 000 ₽ 20-го"})
    assert r.status_code == 200
    j = r.json()
    assert j["event"]["direction"] == "in" and j["event"]["amount"] == 300000 and j["event"]["date"] == "2026-11-20"
    assert j["saved"]["id"].startswith("man-")


def test_sync_all_sources(stub, auth):
    for name in ("tax_calendar", "1c", "bank", "registry", "contracts", "invoices"):
        r = stub.post(f"/api/companies/S02/integrations/{name}/sync", headers=auth)
        assert r.status_code == 200, (name, r.text)
        j = r.json()
        assert j["name"] == name and j["status"] == "ok" and "synced_at" in j and isinstance(j["events_added"], int)
    events = stub.get("/api/companies/S02/events", headers=auth).json()
    sources = {e["source"] for e in events}
    assert {"tax_calendar", "1c", "bank", "open_registry"} <= sources
    anchor = [e for e in events if e.get("counterparty") == "АО «ДонТрансЛогистика»" and e["status"] != "paid"]
    assert anchor and anchor[0]["status"] == "overdue" and "Риск задержки" in anchor[0]["note"]
    assert stub.post("/api/companies/S02/integrations/nope/sync", headers=auth).status_code == 422
    st = stub.get("/api/companies/S02/integrations", headers=auth).json()
    assert {x["name"] for x in st} >= {"tax_calendar", "1c", "bank", "registry", "contracts", "invoices", "manual"}
    checks = stub.get("/api/companies/S02/counterparties/checks", headers=auth).json()
    assert any(c["risk_level"] == "high" for c in checks)


def test_upload_source_file(stub, auth):
    csv_text = ("number;direction;counterparty_name;counterparty_inn;amount;issue_date;due_date;paid_amount;note\n"
                "77;in;ООО «Новый клиент»;0012345678;150000;2026-10-10;2026-10-20;0;\n"
                "78;out;ООО «Поставщик»;0087654321;90000;2026-10-20;2026-11-03;0;\n")
    r = stub.post("/api/companies/S02/integrations/invoices/upload", headers=auth,
                  files={"file": ("inv.csv", csv_text.encode("utf-8"), "text/csv")})
    assert r.status_code == 200 and r.json()["events_added"] == 2
    ev = {e["id"]: e for e in stub.get("/api/companies/S02/events", headers=auth).json()}
    statuses = sorted(e["status"] for e in ev.values() if (e.get("counterparty") or "").startswith("ООО «Новый"))
    assert statuses == ["overdue"]
    r = stub.post("/api/companies/S02/integrations/1c/upload", headers=auth, files={"file": ("x.json", b"{bad", "application/json")})
    assert r.status_code == 400 and "Не удалось прочитать" in r.json()["detail"]


def test_transactions_endpoint(stub, auth):
    rows = [{"date": "2026-10-26", "amount": 57900, "direction": "out", "counterparty_name": "ПАО «Банк»",
             "counterparty_inn": "0068275202", "purpose": "Погашение кредита", "balance_eod": 2463414.4},
            {"operation_date": "2026-10-26", "amount": "1 000,50", "direction": "Поступление", "counterparty_name": "ООО «А»"}]
    r = stub.post("/api/companies/S02/transactions", headers=auth, json=rows)
    assert r.status_code == 200, r.text
    ForecastResult.model_validate(r.json())
    r = stub.post("/api/companies/S02/transactions", headers=auth, json=[{"amount": 5}])
    assert r.status_code == 422 and "Ни одна операция не принята" in r.json()["detail"]
    assert stub.post("/api/companies/S02/transactions", headers=auth, json=[]).status_code == 400


def test_no_jargon_in_sync_messages(stub, auth):
    for name in ("tax_calendar", "1c", "bank", "registry", "contracts", "invoices"):
        msg = stub.post(f"/api/companies/S01/integrations/{name}/sync", headers=auth).json().get("message", "")
        assert not any(w in msg.lower() for w in ("мок", "post /", "json", "p50", "severity")), (name, msg)


def test_openapi_docs(stub):
    assert stub.get("/docs").status_code == 200
    spec = stub.get("/openapi.json").json()
    assert "/api/companies/{cid}/forecast" in spec["paths"]
    assert "ForecastResult" in spec["components"]["schemas"]
