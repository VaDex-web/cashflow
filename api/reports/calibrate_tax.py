from __future__ import annotations

import pandas as pd

from .split import ROOT, split


def main() -> None:
    dev = set(split()["dev"])
    df = pd.read_csv(ROOT / "data" / "raw" / "all_operations.csv", sep=";", dtype={"counterparty_inn": str}, encoding="utf-8-sig")
    df = df[df["company_id"].isin(dev)]
    df["ym"] = pd.to_datetime(df["operation_date"]).dt.to_period("M")
    out = df[df["direction"] == "Списание"]
    text = out["payment_purpose"].fillna("").str.lower()
    tax = out[text.str.contains(r"енп|единый налог|енс")]
    pay = out[text.str.contains(r"заработн")]
    t = tax.groupby(["company_id", "ym"])["amount"].sum()
    p = pay.groupby(["company_id", "ym"])["amount"].sum().groupby(level=0).shift(1)
    j = pd.concat([t.rename("tax"), p.rename("pay")], axis=1).dropna().reset_index()
    j = j[j["ym"].dt.month.isin([2, 5, 8, 11])]
    r = j["tax"] / j["pay"]
    print(f"dev-компаний: {j['company_id'].nunique()}, месяцев: {len(j)}; доля ЕНП от зарплаты: медиана {r.median():.3f} "
          f"(25% — {r.quantile(.25):.3f}, 75% — {r.quantile(.75):.3f})")


if __name__ == "__main__":
    main()
