"""Категоризация: правила, память контрагента, ML, качество."""
from pathlib import Path

import numpy as np
import pandas as pd

from cashflow_core import categorize, load_statement
from cashflow_core.categorize import classification_metrics, evaluate_categorization, rule_category
from datagen import generate_statement


def test_key_rules():
    assert rule_category("ЕНП", "", "out")[0] == "taxes"
    assert rule_category("Единый налоговый платёж", "", "out")[0] == "taxes"
    assert rule_category("Оплата по счету № 5 за товар. В т.ч. НДС 20% - 100.00", "ООО «А»", "out")[0] == "suppliers"
    assert rule_category("Перечисление заработной платы (аванс) за май", "ПАО «Банк»", "out")[0] == "payroll"
    assert rule_category("Плата за аренду POS-терминалов за май", "ПАО «Банк»", "out")[0] == "bank_fees"
    assert rule_category("Оплата аренды нежилого помещения", "", "out")[0] == "rent"
    assert rule_category("Перевод собственных средств на расчетный счет в АО «Б»", "", "out")[0] == "transfers"
    assert rule_category("Зачисление средств по операциям эквайринга", "ПАО «Банк»", "in")[0] == "revenue"
    assert rule_category("Предоставление беспроцентного займа учредителем", "", "in")[0] == "loans"


def test_confidence_range_and_columns():
    c = categorize(load_statement(generate_statement(days=120)))
    assert {"category", "category_label", "category_confidence"} <= set(c.columns)
    assert c["category_confidence"].between(0, 1).all()


def test_empty_purpose_uses_counterparty_memory():
    df = load_statement(generate_statement(days=200, empty_purpose_share=0.0))
    idx = df.index[(df["counterparty_name"] == "ООО «Арендодатель-01»")][-1]
    df.loc[idx, "purpose"] = ""
    c = categorize(df)
    assert c.loc[idx, "category"] == "rent"
    assert c.loc[idx, "category_source"] in ("counterparty", "ml")


def test_quality_vs_truth_and_gold_set():
    g = generate_statement(days=300, empty_purpose_share=0.05)
    c = categorize(load_statement(g))
    m = classification_metrics(g["true_category"], c["category"])
    assert m["accuracy"] >= 0.95
    gold = pd.read_csv(Path(__file__).parent / "fixtures" / "labeled_purposes.csv", sep=";", dtype=str, keep_default_na=False)
    gdf = pd.DataFrame({"date": pd.Timestamp("2025-09-01"), "amount": 1e4, "direction": gold["direction"],
                        "counterparty_name": gold["counterparty_name"], "counterparty_inn": "", "purpose": gold["purpose"],
                        "balance_eod": np.nan, "source_id": "", "tx_id": [f"g{i}" for i in range(len(gold))],
                        "signed_amount": 0.0})
    assert classification_metrics(gold["category"], categorize(gdf)["category"])["accuracy"] >= 0.9


def test_evaluate_categorization_masked_holdout():
    ev = evaluate_categorization(load_statement(generate_statement(days=300)))
    assert ev["coverage_strong_rules"] > 0.9
    assert ev["ml_holdout_masked_purpose"]["accuracy"] > 0.7
