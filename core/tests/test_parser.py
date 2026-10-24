import numpy as np
import pandas as pd

from cashflow_core import load_statement, to_daily
from cashflow_core.io import parse_number
from datagen import generate_statement, to_csv_bytes


def test_dataset_format_maps_columns_and_keeps_inn_zeros():
    raw = generate_statement(days=60, fmt="dataset")
    df = load_statement(to_csv_bytes(raw))
    assert len(df) == len(raw)
    assert set(df["direction"]) == {"in", "out"}
    assert (df["amount"] > 0).all()
    assert df["counterparty_inn"].str.startswith("00").any(), "ведущие нули ИНН должны сохраниться"
    assert df.attrs["company_id"] == "T001"


def test_messy_format_signed_amounts_commas_and_ru_dates():
    raw = generate_statement(days=120, fmt="messy")
    df = load_statement(to_csv_bytes(raw, sep=";", encoding="cp1251"))
    assert len(df) == len(raw) - 1
    assert df["date"].dt.year.min() >= 2025
    assert (df["amount"] > 0).all()
    assert any("дублир" in w for w in df.attrs["warnings"])
    assert any("не сходится" in w for w in df.attrs["warnings"])


def test_header_preamble_and_comma_separator():
    raw = generate_statement(days=30)
    body = raw[["date", "amount", "direction", "purpose", "balance_eod"]].copy()
    body["date"] = body["date"].dt.strftime("%Y-%m-%d")
    text = "Выписка по счёту 40702810...\nПериод: январь\n\n" + body.to_csv(index=False)
    df = load_statement(text.encode("utf-8"))
    assert len(df) == len(raw)


def test_duplicates_decided_by_balance():
    raw = generate_statement(days=40)
    k = 25
    extra = raw.iloc[[k]].copy()
    raw2 = pd.concat([raw.iloc[:k + 1], extra, raw.iloc[k + 1:]]).reset_index(drop=True)
    day = raw2.loc[k + 1, "date"]
    sign = -1 if raw2.loc[k + 1, "direction"] == "out" else 1
    raw2.loc[raw2["date"] >= day, "balance_eod"] += sign * raw2.loc[k + 1, "amount"]
    assert len(load_statement(raw2)) == len(raw2), "реальный повтор не должен удаляться"
    raw3 = pd.concat([raw.iloc[:k + 1], extra, raw.iloc[k + 1:]]).reset_index(drop=True)
    assert len(load_statement(raw3)) == len(raw)


def test_parse_number_variants():
    assert parse_number("1 234,56") == 1234.56
    assert parse_number("1,234.56") == 1234.56
    assert parse_number("(500)") == -500
    assert parse_number("−300 ₽") == -300
    assert parse_number("12345.67") == 12345.67
    assert np.isnan(parse_number("abc"))


def test_garbage_never_raises():
    for bad in [b"", b"hello;world\n1;2\n", pd.DataFrame(), pd.DataFrame({"x": [1, 2]}), "/no/such/file.csv"]:
        df = load_statement(bad)
        assert len(df) == 0
        assert df.attrs["warnings"]


def test_daily_alignment_and_balance_identity():
    df = load_statement(generate_statement(days=90))
    d = to_daily(df)
    assert (d.index == pd.date_range(d.index[0], d.index[-1], freq="D")).all()
    assert np.allclose(d["balance"].diff().iloc[1:], d["net"].iloc[1:], atol=0.01)
    assert not d["mismatch"].any()
