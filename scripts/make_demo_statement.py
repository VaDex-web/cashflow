"""Выписка компании из датасета организаторов «по состоянию на дату» — для демо прогноза из прошлого.

    python scripts/make_demo_statement.py C124 2025-09-16
    → data/demo/C124_по_2025-09-16.csv  (тот же формат: UTF-8 с BOM, «;»; только операции до даты включительно)

Файл производный от data/raw и в git не попадает (data/demo/ в .gitignore).
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("company", help="company_id, например C124")
    ap.add_argument("until", help="последняя дата операций, YYYY-MM-DD")
    ap.add_argument("--raw", default=str(ROOT / "data" / "raw" / "statements"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    src = Path(a.raw) / f"{a.company}.csv"
    out = Path(a.out) if a.out else ROOT / "data" / "demo" / f"{a.company}_по_{a.until}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(src, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))
    head, body = rows[0], rows[1:]
    i = head.index("operation_date")
    keep = [r for r in body if r[i] <= a.until]
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f, delimiter=";", lineterminator="\n").writerows([head, *keep])
    print(f"{out}: {len(keep)} операций из {len(body)}, последняя дата {keep[-1][i] if keep else '—'}")


if __name__ == "__main__":
    main()
