"""Устойчивость на «плохих» выписках (новый датасет организаторов может быть любым): весь конвейер API
отвечает 200 или понятной ошибкой 4xx, но не падает. Прогоняется на заглушке и, если есть, на настоящем ядре."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from .conftest import core_available, login, make_client

HEADER = "company_id;operation_id;operation_date;amount;direction;counterparty_inn;counterparty_name;payment_purpose;balance_eod\n"


def _rows(n: int, start: date = date(2026, 6, 1), step: int = 1, inflow_only: bool = False, empty: bool = False,
          overdraft: bool = False, dup: bool = False, gap: bool = False) -> str:
    out, bal = [], (-200_000.0 if overdraft else 300_000.0)
    d = start
    for i in range(n):
        d += timedelta(days=step)
        if gap and 10 <= i < 30:
            continue
        inflow = inflow_only or i % 3 == 0
        amt = 120_000.0 if inflow else 45_000.0
        bal += amt if inflow else -amt
        inn = "" if empty else ("0012345678" if inflow else "0087654321")
        purpose = "" if empty else ("Оплата по счету №%d" % i if inflow else "Единый налоговый платеж" if i % 7 == 0 else "Оплата поставщику")
        name = "" if empty else ("ООО «Клиент»" if inflow else "ООО «Поставщик»")
        line = f"X1;{i};{d.isoformat()};{amt:.2f};{'Поступление' if inflow else 'Списание'};{inn};{name};{purpose};{bal:.2f}\n"
        out.append(line)
        if dup and i % 10 == 0:
            out.append(line)
    return HEADER + "".join(out)


CASES = {
    "одна операция": _rows(1),
    "пять операций": _rows(5),
    "только поступления": _rows(60, inflow_only=True),
    "пустые ИНН и назначения": _rows(80, empty=True),
    "овердрафт с первого дня": _rows(120, overdraft=True),
    "дубли строк": _rows(120, dup=True),
    "пропуск в несколько недель": _rows(150, gap=True),
    "редкие операции": _rows(20, step=9),
}


def _pipeline(c, name: str, text: str) -> None:
    h = login(c)
    r = c.post("/api/companies", headers=h, files={"file": (f"{name}.csv", text.encode("utf-8-sig"), "text/csv")})
    assert r.status_code == 200, (name, r.text)
    cid = r.json()["company_id"]
    f = c.get(f"/api/companies/{cid}/forecast", headers=h)
    assert f.status_code == 200, (name, f.text)
    assert isinstance(f.json().get("warnings", []), list)
    for s in ("tax_calendar", "bank", "registry", "1c", "contracts", "invoices"):
        assert c.post(f"/api/companies/{cid}/integrations/{s}/sync", headers=h).status_code == 200, (name, s)
    for path in ("forecast", "alerts", "recurring", "categories", "events", "plan-fact", "settings"):
        r = c.get(f"/api/companies/{cid}/{path}", headers=h)
        assert r.status_code == 200, (name, path, r.text)
    sc = c.post(f"/api/companies/{cid}/scenarios/run", headers=h, json={"type": "revenue_drop", "params": {"percent": 20}})
    assert sc.status_code == 200, (name, sc.text)
    tx = c.post(f"/api/companies/{cid}/transactions", headers=h,
                json=[{"date": "2026-12-01", "amount": 1000, "direction": "in", "counterparty_name": "", "purpose": ""}])
    assert tx.status_code == 200, (name, tx.text)


@pytest.mark.parametrize("name", list(CASES))
def test_edge_cases_stub(tmp_path, name):
    with make_client(tmp_path, stub=True) as c:
        _pipeline(c, name, CASES[name])


@pytest.mark.parametrize("name", list(CASES))
def test_edge_cases_real_core(tmp_path, name):
    if not core_available():
        pytest.skip("cashflow_core недоступен")
    with make_client(tmp_path, stub=False) as c:
        _pipeline(c, name, CASES[name])
