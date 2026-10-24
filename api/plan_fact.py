from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .textfmt import day_month, rub

_TAX_RX = re.compile(r"(?i)енп|единый налог|енс|налог|фнс|страхов")
_PAY_RX = re.compile(r"(?i)заработн|зарплат|\(аванс\)|аванс по заработ|реестр")
_LOAN_RX = re.compile(r"(?i)кредит|лизинг|займ")


@dataclass
class Match:
    event_id: str
    status: str
    paid_date: date | None = None
    paid_amount: float | None = None
    late_days: int = 0
    tx_index: int | None = None


@dataclass
class EventView:
    id: str
    type: str
    direction: str
    amount: float
    date: date
    source: str
    status: str
    counterparty: str = ""
    counterparty_inn: str = ""
    note: str = ""
    status_locked: bool = False
    paid_date: date | None = None
    paid_amount: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _norm(s: str) -> str:
    s = re.sub(r"(?i)\b(ооо|ао|пао|зао|ип|мку|мбу|муп)\b", " ", s or "")
    return re.sub(r"[^0-9a-zа-яё]+", " ", s.lower()).strip()


def _same_cp(ev: EventView, name: str, inn: str) -> bool:
    if ev.counterparty_inn and inn and ev.counterparty_inn == inn:
        return True
    a, b = _norm(ev.counterparty), _norm(name)
    return bool(a) and bool(b) and (a == b or (len(a) > 4 and a in b) or (len(b) > 4 and b in a))


def _window(ev: EventView) -> tuple[int, int, float, float, bool]:
    if ev.type == "tax":
        return 5, 5, 0.5, 1.6, False
    if ev.type == "payroll":
        return 4, 3, 0.85, 1.15, False
    if ev.type == "loan":
        return 3, 5, 0.95, 1.05, False
    if ev.counterparty:
        return (10, 45, 0.3, 1.05, True) if ev.direction == "in" else (5, 15, 0.3, 1.05, True)
    return 3, 3, 0.98, 1.02, False


def reconcile(events: Iterable[EventView], tx: pd.DataFrame, as_of: date, grace_days: int = 1) -> list[Match]:
    out: list[Match] = []
    if tx is None or not len(tx):
        return out
    t = tx.reset_index(drop=True).copy()
    t["_d"] = pd.to_datetime(t["date"]).dt.date
    t["_text"] = (t["purpose"].astype(str) + " " + t["counterparty_name"].astype(str))
    used: set[int] = set()
    for ev in sorted(events, key=lambda e: (e.date, -e.amount)):
        if ev.status_locked:
            continue
        before, after, lo, hi, need_cp = _window(ev)
        cand = t[(t["direction"] == ev.direction) & (t["_d"] >= ev.date - timedelta(days=before))
                 & (t["_d"] <= min(as_of, ev.date + timedelta(days=after)))]
        best, best_score = None, None
        for i, r in cand.iterrows():
            if i in used:
                continue
            ratio = float(r["amount"]) / max(ev.amount, 1.0)
            if not lo <= ratio <= hi:
                continue
            if ev.type == "tax" and not _TAX_RX.search(r["_text"]):
                continue
            if ev.type == "payroll" and not _PAY_RX.search(r["_text"]):
                continue
            if ev.type == "loan" and not (_LOAN_RX.search(r["_text"]) or _same_cp(ev, r["counterparty_name"], r["counterparty_inn"])):
                continue
            if need_cp and not _same_cp(ev, str(r["counterparty_name"]), str(r["counterparty_inn"])):
                continue
            score = abs((r["_d"] - ev.date).days) + 30 * abs(1 - ratio)
            if best_score is None or score < best_score:
                best, best_score = i, score
        if best is not None:
            r = t.loc[best]
            used.add(best)
            paid = float(r["amount"])
            status = "paid" if paid >= 0.9 * ev.amount or ev.type in ("tax",) else (
                "overdue" if ev.date < as_of - timedelta(days=grace_days) else "expected")
            out.append(Match(ev.id, status, r["_d"], paid, max(0, (r["_d"] - ev.date).days), int(best)))
        elif ev.date < as_of - timedelta(days=grace_days) and ev.status != "paid":
            out.append(Match(ev.id, "overdue"))
        elif ev.status == "overdue" and ev.date > as_of:
            out.append(Match(ev.id, "expected"))
    return out


def _recurring_dates(p: dict[str, Any], start: date, end: date) -> list[date]:
    from .integrations.base import next_business_day, prev_business_day

    try:
        nd = date.fromisoformat(str(p["next_date"])[:10])
        period = max(1, int(round(float(p["period_days"]))))
    except (KeyError, ValueError, TypeError):
        return []
    out = []
    if 27 <= period <= 32:
        name = str(p.get("name", "")).lower()
        shift = next_business_day if ("налог" in name or p.get("direction") == "in") else prev_business_day
        y, m = nd.year, nd.month
        for _ in range(36):
            last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
            d = shift(date(y, m, min(nd.day, last)))
            if d < start:
                break
            if d <= end:
                out.append(d)
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        return sorted(out)
    d = nd
    while d > end:
        d -= timedelta(days=period)
    while d >= start:
        out.append(d)
        d -= timedelta(days=period)
    return sorted(out)


def build(tx: pd.DataFrame, events: list[EventView], recurring: list[dict[str, Any]], as_of: date, matches: list[Match],
          weeks: int = 8, period: str = "week") -> list[dict[str, Any]]:
    t = tx.copy() if tx is not None else pd.DataFrame(columns=["date", "amount", "direction", "counterparty_name", "counterparty_inn", "purpose"])
    t["_d"] = pd.to_datetime(t["date"]).dt.date
    if period == "day":
        starts = [as_of - timedelta(days=k) for k in range(13, -1, -1)]
        step = timedelta(days=1)
    else:
        monday = as_of - timedelta(days=as_of.weekday())
        starts = [monday - timedelta(days=7 * k) for k in range(weeks - 1, -1, -1)]
        step = timedelta(days=7)
    w0 = starts[0]
    by_id = {m.event_id: m for m in matches}
    matched_tx = {m.tx_index for m in matches if m.tx_index is not None}
    ev_dates = [(e.direction, e.date, e.amount) for e in events]

    rec_occ: list[tuple[str, date, float, str, float]] = []
    for p in recurring or []:
        if float(p.get("period_days") or 0) < 5:
            continue
        for d in _recurring_dates(p, w0 - timedelta(days=84), as_of + timedelta(days=1)):
            amt = float(p.get("amount_avg") or 0.0)
            covered = any(dr == p["direction"] and abs((d - ed).days) <= 5 and 0.5 <= amt / max(ea, 1.0) <= 2.0
                          for dr, ed, ea in ev_dates)
            if not covered and amt > 0:
                rec_occ.append((p["direction"], d, amt, str(p.get("name", "")), float(p.get("confidence") or 0)))

    hist = t[(t["_d"] >= w0 - timedelta(days=84)) & (t["_d"] < w0)]
    days_hist = max(1, min(84, (w0 - min(t["_d"])).days)) if len(t) else 84
    bucket_days = step.days
    base: dict[str, float] = {}
    for dr in ("in", "out"):
        tot = float(hist.loc[hist["direction"] == dr, "amount"].sum())
        rec = sum(a for d_, dd, a, _, _ in rec_occ if d_ == dr and w0 - timedelta(days=84) <= dd < w0)
        evs = sum(e.amount for e in events if e.direction == dr and w0 - timedelta(days=84) <= e.date < w0)
        base[dr] = max(0.0, (tot - rec - evs) / days_hist * bucket_days)

    tx_amounts = {dr: float(np.median(t.loc[t["direction"] == dr, "amount"])) if (t["direction"] == dr).sum() >= 10 else 0.0
                  for dr in ("in", "out")}
    rows = []
    for s in starts:
        e_ = s + step
        planned = {dr: base[dr] for dr in ("in", "out")}
        devs: list[dict[str, str]] = []
        for ev in events:
            if s <= ev.date < e_:
                planned[ev.direction] += ev.amount
        for dr, d, a, name, conf in rec_occ:
            if s <= d < e_:
                planned[dr] += a
        week_tx = t[(t["_d"] >= s) & (t["_d"] < e_)]
        actual = {dr: float(week_tx.loc[week_tx["direction"] == dr, "amount"].sum()) for dr in ("in", "out")}

        for ev in sorted(events, key=lambda x: x.date):
            if not (s <= ev.date < e_) or ev.date > as_of:
                continue
            m = by_id.get(ev.id)
            who = ev.counterparty or {"tax": "Налоговый платёж", "payroll": "Зарплата", "loan": "Платёж по кредиту"}.get(ev.type, "Платёж")
            what = _short_note(ev) or " платёж"
            status = m.status if m else ev.status
            if status == "overdue" and not (m and m.paid_amount):
                if ev.direction == "in":
                    devs.append({"event_id": ev.id, "text": f"{who} не оплатил{what} на {rub(ev.amount)} (ожидали {day_month(ev.date)})"})
                else:
                    devs.append({"event_id": ev.id, "text": f"Не прошёл платёж {rub(ev.amount)}: {who} (план — {day_month(ev.date)})"})
            elif m and m.paid_amount is not None:
                if m.paid_amount < 0.9 * ev.amount and ev.type != "tax":
                    devs.append({"event_id": ev.id, "text": f"{who}: оплата{what} меньше на {rub(ev.amount - m.paid_amount)} (частичная оплата)"})
                elif m.late_days >= 3 and ev.direction == "in":
                    devs.append({"event_id": ev.id, "text": f"{who} оплатил{what} с опозданием на {m.late_days} дн. ({day_month(m.paid_date)} вместо {day_month(ev.date)})"})
                elif ev.type == "tax" and abs(m.paid_amount - ev.amount) > max(0.15 * ev.amount, 30_000):
                    diff = m.paid_amount - ev.amount
                    devs.append({"event_id": ev.id, "text": f"Налоговый платёж {'больше' if diff > 0 else 'меньше'} оценки на {rub(abs(diff))}"})
        for dr, d, a, name, conf in rec_occ:
            if s <= d < e_ and d <= as_of - timedelta(days=2) and d >= as_of - timedelta(days=14) and conf >= 0.7 and dr == "in":
                hit = t[(t["direction"] == dr) & (t["_d"] >= d - timedelta(days=4)) & (t["_d"] <= min(as_of, d + timedelta(days=4)))
                        & (t["amount"] >= 0.6 * a) & (t["amount"] <= 1.4 * a)]
                if not len(hit):
                    devs.append({"event_id": f"rec-{d.isoformat()}", "text": f"Регулярное поступление «{name}» не пришло (ожидали ~{day_month(d)}, около {rub(a)})"})
        big = []
        for i, r in week_tx.iterrows():
            if i in matched_tx:
                continue
            dr = r["direction"]
            thr = max(0.3 * planned[dr], 3 * tx_amounts[dr], 50_000)
            if float(r["amount"]) >= thr and not re.search(r"(?i)собственн", str(r["purpose"])):
                near_rec = any(rd == dr and abs((r["_d"] - rdd).days) <= 4 and 0.6 <= float(r["amount"]) / max(ra, 1) <= 1.4
                               for rd, rdd, ra, _, _ in rec_occ)
                if not near_rec:
                    big.append(r)
        for r in sorted(big, key=lambda x: -float(x["amount"]))[:2]:
            kind = "поступление" if r["direction"] == "in" else "списание"
            cp = str(r["counterparty_name"] or "")
            devs.append({"event_id": f"tx-{r['_d'].isoformat()}-{int(r['amount'])}",
                         "text": f"Внеплановое {kind} {rub(float(r['amount']))}" + (f" — {cp}" if cp else "") + f" ({day_month(r['_d'])})"})
        if s <= as_of < e_ and period == "week":
            pass
        else:
            if planned["in"] > 0 and actual["in"] < 0.8 * planned["in"] and planned["in"] - actual["in"] >= 50_000:
                devs.append({"event_id": f"period-{s.isoformat()}-in", "text": f"Поступления ниже плана на {rub(planned['in'] - actual['in'])} ({actual['in'] / planned['in'] - 1:.0%})"})
            if planned["out"] > 0 and actual["out"] > 1.2 * planned["out"] and actual["out"] - planned["out"] >= 50_000:
                devs.append({"event_id": f"period-{s.isoformat()}-out", "text": f"Списания выше плана на {rub(actual['out'] - planned['out'])} (+{actual['out'] / planned['out'] - 1:.0%})"})
        rows.append({"period": s.isoformat(), "planned_in": round(planned["in"], 2), "actual_in": round(actual["in"], 2),
                     "planned_out": round(planned["out"], 2), "actual_out": round(actual["out"], 2), "deviations": devs})
    return rows


def _short_note(ev: EventView) -> str:
    m = re.search(r"(?i)(сч[её]т[^,.;]*?№\s*[\w/-]+)", ev.note or "")
    if m:
        return " " + m.group(1).lower()
    m = re.search(r"(?i)(договор[^,.;:]*?№\s*[\w/-]+)", ev.note or "")
    return f" по {m.group(1).lower().replace('договор', 'договору', 1)}" if m else ""
