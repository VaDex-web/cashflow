import csv
import json

import pandas as pd

from cashflow_core.predict import CSV_COLUMNS, predict
from datagen import generate_statement


def _dataset(tmp):
    a = generate_statement(days=300, seed=1, fmt="dataset")
    b = generate_statement(days=40, seed=2, fmt="dataset")
    b["company_id"] = "T002"
    b["payment_purpose"] = ""
    b.loc[b.index[:5], "counterparty_inn"] = ""
    c = a.iloc[:1].copy()
    c["company_id"] = "T003"
    allops = pd.concat([a, b, c]).drop(columns=["true_category"])
    f = tmp / "all_operations.csv"
    allops.to_csv(f, sep=";", index=False, encoding="utf-8-sig")
    return f


def test_predict_files_rows_and_determinism(tmp_path=None):
    from pathlib import Path
    import tempfile

    tmp = Path(tmp_path or tempfile.mkdtemp())
    src = _dataset(tmp)
    c1, j1, res = predict(src, tmp / "p1.csv", horizon=30, n_sims=300, workers=1)
    c2, j2, _ = predict(src, tmp / "p2.csv", horizon=30, n_sims=300, workers=2)
    assert c1.read_bytes() == c2.read_bytes() and j1.read_bytes() == j2.read_bytes(), "вывод должен быть детерминированным"
    rows = list(csv.reader(open(c1, encoding="utf-8"), delimiter=";"))
    assert rows[0] == CSV_COLUMNS
    assert len(rows) - 1 == 3 * 30
    by = {}
    for r in rows[1:]:
        by.setdefault(r[0], []).append(r)
        assert float(r[3]) <= float(r[2]) <= float(r[4])
    assert set(by) == {"T001", "T002", "T003"} and all(len(v) == 30 for v in by.values())
    data = json.loads(j1.read_text(encoding="utf-8"))
    assert [c["company_id"] for c in data["companies"]] == ["T001", "T002", "T003"]
    for c in data["companies"]:
        for k in c["risks"]:
            assert 0 <= k["probability"] <= 1 and k["kind"] in ("gap", "below_comfort") and k["shortfall_amount"] >= 0
    first = {c["company_id"]: c["as_of"] for c in data["companies"]}
    assert rows[1][1] > first["T001"], "прогноз начинается после последней даты выписки"
