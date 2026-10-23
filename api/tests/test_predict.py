"""Прогноз для контрольного датасета: CLI-обёртка и POST /api/predict без входа."""
from __future__ import annotations

import csv
import io
import json

import pytest

from api import predict as pr

from .conftest import SYN, core_available, make_client

MULTI = ("company_id;operation_id;operation_date;amount;direction;counterparty_inn;counterparty_name;payment_purpose;balance_eod\n"
         "A1;A1-1;2026-09-01;100000.00;Поступление;0012345678;ООО «Клиент»;Оплата;600000.00\n"
         "A1;A1-2;2026-09-02;20000.00;Списание;;;;580000.00\n"
         "B2;B2-1;2026-08-03;5000.00;Списание;;Физическое лицо;;-15000.00\n")


def test_read_inputs_folder_and_dedup(tmp_path):
    d = tmp_path / "set"
    (d / "statements").mkdir(parents=True)
    (d / "statements" / "A1.csv").write_text(MULTI.split("B2;")[0], encoding="utf-8-sig")
    (d / "all_operations.csv").write_text(MULTI, encoding="utf-8-sig")
    (d / "companies.csv").write_text("company_id;company_name\nA1;x\n", encoding="utf-8-sig")
    got = pr.read_inputs(d)
    assert sorted(got) == ["A1", "B2"] and len(got["A1"]) == 2
    with pytest.raises(pr.PredictError):
        pr.read_inputs(tmp_path / "nope")


def test_bad_file_message():
    with pytest.raises(pr.PredictError, match="нет колонок"):
        pr.read_csv_bytes("date;sum\n2026-01-01;5\n".encode(), "x.csv")
    with pytest.raises(pr.PredictError, match="пустой"):
        pr.read_csv_bytes(b"", "x.csv")


@pytest.mark.skipif(not core_available(), reason="cashflow_core недоступен")
def test_cli_run_and_files(tmp_path):
    comps = pr.read_inputs(SYN / "statements" / "S02.csv")
    rows, meta = pr.run(comps, horizon=30, n_sims=300)
    assert len(rows) == 30 and rows[0]["date"] == "2026-10-24" and rows[0]["company_id"] == "S02"
    assert all(r["balance_low"] <= r["balance_forecast"] <= r["balance_high"] for r in rows)
    c, j = pr.write(rows, meta, tmp_path / "out" / "pred.csv")
    head = c.read_text(encoding="utf-8").splitlines()[0]
    assert head == "company_id;date;balance_forecast;balance_low;balance_high"
    info = json.loads(j.read_text(encoding="utf-8"))["companies"][0]
    assert info["as_of"] == "2026-10-23" and all({"date", "shortfall_amount", "probability"} <= set(r) for r in info["risks"])
    rows2, _ = pr.run(comps, horizon=30, n_sims=300)
    assert rows == rows2                                     # детерминированно (seed фиксирован)


@pytest.mark.skipif(not core_available(), reason="cashflow_core недоступен")
def test_short_and_broken_histories_do_not_fail():
    comps = {cid: part.reset_index(drop=True) for cid, part in pr.read_csv_bytes(MULTI.encode()).groupby("company_id")}
    rows, meta = pr.run(comps, horizon=10, n_sims=200)
    assert {r["company_id"] for r in rows} == {"A1", "B2"} and len(rows) == 20
    b2 = next(x for x in meta["companies"] if x["company_id"] == "B2")
    assert b2["as_of"] == "2026-08-03" and rows[-1]["date"] == "2026-08-13"


def test_endpoint_without_login(tmp_path):
    with make_client(tmp_path, stub=True) as c:
        raw = (SYN / "statements" / "S05.csv").read_bytes()
        r = c.post("/api/predict?horizon=14", files={"file": ("S05.csv", raw, "text/csv")})
        assert r.status_code == 200, r.text
        j = r.json()
        assert len(j["forecast"]) == 14 and j["companies"][0]["company_id"] == "S05"
        r = c.post("/api/predict?horizon=7&format=csv", files={"file": ("m.csv", MULTI.encode("utf-8-sig"), "text/csv")})
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        table = list(csv.DictReader(io.StringIO(r.text), delimiter=";"))
        assert len(table) == 14 and {t["company_id"] for t in table} == {"A1", "B2"}
        r = c.post("/api/predict", files={"file": ("bad.csv", b"a;b\n1;2\n", "text/csv")})
        assert r.status_code == 400 and "нет колонок" in r.json()["detail"]
