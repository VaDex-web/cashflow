from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _core_split() -> dict[str, list[str]] | None:
    p = Path(os.getenv("CORE_PATH", ROOT / "core")) / "reports" / "split.json"
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(d, dict) and d.get("dev") and d.get("holdout"):
            return {"dev": list(d["dev"]), "holdout": list(d["holdout"]), "source": str(p)}
    return None


def is_holdout(company_id: str) -> bool:
    return int(hashlib.sha1(f"cashflow-holdout:{company_id}".encode()).hexdigest()[:8], 16) % 10 < 3


def split(companies_csv: Path | None = None) -> dict[str, list[str]]:
    core = _core_split()
    if core:
        return core
    path = companies_csv or ROOT / "data" / "raw" / "companies.csv"
    ids = [r["company_id"] for r in csv.DictReader(path.open(encoding="utf-8-sig"), delimiter=";")]
    return {"dev": [c for c in ids if not is_holdout(c)], "holdout": [c for c in ids if is_holdout(c)],
            "source": "hash(company_id) % 10 < 3"}


if __name__ == "__main__":
    s = split()
    print(f"dev: {len(s['dev'])}, holdout: {len(s['holdout'])} ({s['source']})")
    print("holdout:", ", ".join(s["holdout"]))
