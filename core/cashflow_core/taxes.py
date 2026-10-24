from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .calendar_ru import shift_to_business_day

REGIME_LABELS = {
    "usn_income": "УСН «Доходы» (6%)",
    "usn_income_expense": "УСН «Доходы минус расходы» (15%)",
    "osno": "ОСНО (плательщик НДС)",
    "eshn": "ЕСХН",
    "unknown": "не удалось определить",
}

_NDS_RX = r"(?i)(?:в\s*т\.?\s*ч\.?\s*ндс|в\s+том\s+числе\s+ндс)(?!\s*0\s*%)"


_REGIME_MONTHS: dict[str, set[int] | None] = {
    "usn_income": {3, 4, 7, 10},
    "usn_income_expense": {3, 4, 7, 10},
    "eshn": {3, 7},
    "osno": None,
    "unknown": None,
}


def _ym(d: pd.Timestamp | date) -> int:
    return d.year * 12 + d.month - 1


def _prev_quarter_months(mi: int) -> list[int]:
    q_start = mi - (mi % 12) % 3
    return [q_start - 3, q_start - 2, q_start - 1]


@dataclass
class TaxModel:
    base: float = 0.0
    ratio_by_moy: dict[int, float] = field(default_factory=dict)
    revenue_by_ym: dict[int, float] = field(default_factory=dict)
    anchor_day: int = 28
    regime: dict[str, Any] = field(default_factory=dict)
    history_months: int = 0

    def expected_excess(self, mi: int) -> tuple[float, float]:
        moy = mi % 12 + 1
        prev_rev = sum(self.revenue_by_ym.get(m, 0.0) for m in _prev_quarter_months(mi))
        if moy in self.ratio_by_moy:
            return max(0.0, self.ratio_by_moy[moy] * prev_rev), 0.25
        return 0.0, 0.0

    def items(self, start: date, end: date) -> list[dict[str, Any]]:
        out = []
        mi = _ym(start)
        while True:
            nominal = date(mi // 12, mi % 12 + 1, min(self.anchor_day, 28))
            d = shift_to_business_day(nominal, "forward")
            if d > end:
                break
            if d >= start:
                amt, cv = self.expected_excess(mi)
                if amt > 1000:
                    out.append({"date": d, "amount": amt, "cv": cv, "month": nominal.month})
            mi += 1
        return out


def fit_tax_model(df: pd.DataFrame, as_of: date | None = None) -> TaxModel:
    tm = TaxModel()
    if df is None or not len(df) or "category" not in df.columns:
        return tm
    d = df.copy()
    d.attrs = {}
    d["date"] = pd.to_datetime(d["date"])
    d["ym"] = d["date"].dt.year * 12 + d["date"].dt.month - 1
    rev = d[(d["direction"] == "in") & (d["category"] == "revenue")].groupby("ym")["amount"].sum()
    tm.revenue_by_ym = {int(k): float(v) for k, v in rev.items()}
    taxes = d[(d["direction"] == "out") & (d["category"] == "taxes")]
    tm.history_months = int(d["ym"].nunique())
    tm.regime = estimate_tax_regime(df)
    if not len(taxes):
        return tm
    tm.anchor_day = int(taxes["date"].dt.day.mode().iloc[0]) if len(taxes) else 28
    first_full = int(d["ym"].min()) + 1
    last_full = int(d["ym"].max()) - (0 if (as_of or d["date"].max().date()).day >= 28 else 1)
    months = range(first_full, last_full + 1)
    t_by = taxes.groupby("ym")["amount"].sum()
    totals = np.array([float(t_by.get(m, 0.0)) for m in months])
    if not len(totals):
        return tm
    tm.base = float(np.median(totals))
    ratios: dict[int, list[float]] = {}
    for m, tot in zip(months, totals):
        prev_rev = sum(tm.revenue_by_ym.get(x, 0.0) for x in _prev_quarter_months(m))
        prev_known = all(x >= int(d["ym"].min()) for x in _prev_quarter_months(m))
        excess = tot - tm.base
        if prev_known and prev_rev > 0 and excess > max(0.3 * tm.base, 5000):
            ratios.setdefault(m % 12 + 1, []).append(excess / prev_rev)
    allowed = _REGIME_MONTHS.get(tm.regime.get("regime", "unknown"))
    tm.ratio_by_moy = {moy: float(min(0.2, np.average(v, weights=np.arange(1, len(v) + 1))))
                       for moy, v in ratios.items() if allowed is None or moy in allowed}
    if not tm.ratio_by_moy and tm.regime.get("regime") in ("usn_income",) and tm.history_months < 13:
        tm.ratio_by_moy = {4: 0.03, 7: 0.03, 10: 0.03}
        tm.regime["fallback_rates"] = True
    return tm


def estimate_tax_regime(df: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"regime": "unknown", "label": REGIME_LABELS["unknown"], "confidence": 0.0, "evidence": []}
    if df is None or not len(df) or "category" not in df.columns:
        return out
    d = df.copy()
    d.attrs = {}
    d["date"] = pd.to_datetime(d["date"])
    d["ym"] = d["date"].dt.year * 12 + d["date"].dt.month - 1
    rev = d[(d["direction"] == "in") & (d["category"] == "revenue")]
    nds_share = float(rev["purpose"].str.contains(_NDS_RX, regex=True).mean()) if len(rev) else 0.0
    taxes = d[(d["direction"] == "out") & (d["category"] == "taxes")]
    ev = [f"доля поступлений с выделенным НДС: {nds_share:.0%}"]
    if len(taxes) < 3:
        out["evidence"] = ev + ["налоговых платежей слишком мало"]
        return out
    t_by = taxes.groupby("ym")["amount"].sum()
    months = range(int(d["ym"].min()) + 1, int(d["ym"].max()))
    totals = pd.Series({m: float(t_by.get(m, 0.0)) for m in months})
    base = float(totals.median())
    spikes = totals[totals > 1.3 * base + 5000]
    spike_moy = sorted({m % 12 + 1 for m in spikes.index})
    ev.append("месяцы крупных ЕНП: " + (", ".join(map(str, spike_moy)) or "нет"))
    if nds_share > 0.4:
        out.update(regime="osno", confidence=round(min(0.9, 0.5 + nds_share / 2), 2))
    elif spike_moy and set(spike_moy) <= {3, 7} and 7 in spike_moy:
        out.update(regime="eshn", confidence=0.6)
    elif spike_moy and {4, 7, 10} & set(spike_moy):
        rev_m = rev.groupby("ym")["amount"].sum()
        exp_m = d[(d["direction"] == "out") & ~d["category"].isin(["taxes", "transfers", "loans"])].groupby("ym")["amount"].sum()
        r_rev, r_prof = [], []
        for m in spikes.index:
            if m % 12 + 1 not in (4, 7, 10):
                continue
            pq = _prev_quarter_months(m)
            qr = float(sum(rev_m.get(x, 0.0) for x in pq))
            qe = float(sum(exp_m.get(x, 0.0) for x in pq))
            exc = float(spikes[m] - base)
            if qr > 0:
                r_rev.append(exc / qr)
            if qr - qe > 0:
                r_prof.append(exc / (qr - qe))
        rr = float(np.median(r_rev)) if r_rev else np.nan
        rp = float(np.median(r_prof)) if r_prof else np.nan
        ev.append(f"всплеск / выручка квартала ≈ {rr:.1%}" if np.isfinite(rr) else "нет данных о выручке")
        if np.isfinite(rp):
            ev.append(f"всплеск / прибыль квартала ≈ {rp:.1%}")
        if np.isfinite(rp) and 0.09 <= rp <= 0.18 and not (np.isfinite(rr) and 0.025 <= rr <= 0.065):
            out.update(regime="usn_income_expense", confidence=0.6)
        elif np.isfinite(rr) and 0.012 <= rr <= 0.07:
            out.update(regime="usn_income", confidence=0.65)
        elif np.isfinite(rp) and 0.09 <= rp <= 0.25:
            out.update(regime="usn_income_expense", confidence=0.5)
        else:
            out.update(regime="usn_income", confidence=0.35)
    out["label"] = REGIME_LABELS[out["regime"]]
    out["evidence"] = ev
    return out
