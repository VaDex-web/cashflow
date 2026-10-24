from __future__ import annotations

import re
from typing import Any

import pandas as pd

_RULES: list[tuple[str, str, str]] = [
    ("transfers", "*", r"собственн|между своими|депозит"),
    ("taxes", "out", r"енп|единый налог|налог|фнс|енс|страхов\w* взнос"),
    ("payroll", "out", r"заработн|зарплат|аванс по зар|\(аванс\)|премии|самозанят|нпд"),
    ("rent", "out", r"аренд"),
    ("loans", "*", r"кредит|лизинг|займ|транш"),
    ("bank_fees", "out", r"комисси|обслуживан\w* сч"),
    ("utilities", "out", r"электроэнерг|водоснаб|связи|интернет|подписк|лиценз|охран|тко|коммунал"),
    ("revenue", "in", r"эквайринг|оплата|выручк|сбп|реализац|взнос наличных|выплата по отчету|перечисление денежных"),
    ("suppliers", "out", r"оплата|поставк|товар|материал|счет|счёт|упд"),
]
LABELS = {
    "revenue": "Выручка от клиентов", "payroll": "Зарплата", "rent": "Аренда", "taxes": "Налоги и взносы",
    "suppliers": "Поставщики/закупки", "utilities": "Коммунальные/связь/подписки", "loans": "Кредиты и проценты",
    "bank_fees": "Банковские комиссии", "transfers": "Переводы между своими счетами", "other": "Прочее",
}


def categorize_simple(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    cats, conf = [], []
    for purpose, name, direction in zip(out.get("purpose", ""), out.get("counterparty_name", ""), out["direction"]):
        text = f"{purpose} {name}".lower()
        hit = next((c for c, d, rx in _RULES if d in ("*", direction) and re.search(rx, text)), None)
        cats.append(hit or "other")
        conf.append(0.7 if hit else 0.3)
    out["category"] = cats
    out["category_label"] = [LABELS[c] for c in cats]
    out["category_confidence"] = conf
    return out


def summarize(df: pd.DataFrame, limit: int | None = None) -> dict[str, Any]:
    if not len(df):
        return {"summary": [], "transactions": []}
    d = df.copy()
    label = d["category_label"] if "category_label" in d.columns else d["category"].map(lambda c: LABELS.get(c, c))
    d["cat_label"] = label.fillna("Прочее")
    summary = []
    for direction in ("in", "out"):
        part = d[d["direction"] == direction]
        total_dir = float(part["amount"].sum()) or 1.0
        g = part.groupby("cat_label")["amount"].agg(["sum", "count"]).sort_values("sum", ascending=False)
        for cat, row in g.iterrows():
            summary.append({"category": str(cat), "direction": direction, "total": round(float(row["sum"]), 2),
                            "count": int(row["count"]), "share": round(float(row["sum"]) / total_dir, 4)})
    d["dt"] = pd.to_datetime(d["date"])
    d = d.sort_values("dt", ascending=False, kind="stable")
    if limit:
        d = d.head(limit)
    tx = []
    for r in d.itertuples(index=False):
        bal = getattr(r, "balance_eod", None)
        tx.append({"date": r.dt.date().isoformat(), "amount": round(float(r.amount), 2), "direction": r.direction,
                   "counterparty_name": str(getattr(r, "counterparty_name", "") or ""),
                   "counterparty_inn": str(getattr(r, "counterparty_inn", "") or ""),
                   "purpose": str(getattr(r, "purpose", "") or ""),
                   "balance_eod": None if bal is None or pd.isna(bal) else round(float(bal), 2),
                   "category": str(r.cat_label), "category_confidence": round(float(getattr(r, "category_confidence", 0.0) or 0.0), 3)})
    return {"summary": summary, "transactions": tx}
