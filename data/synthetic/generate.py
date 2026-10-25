from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import numpy as np

_HOLIDAYS = {
    2024: ["01-01", "01-02", "01-03", "01-04", "01-05", "01-08", "02-23", "03-08", "04-29", "04-30", "05-01",
           "05-09", "05-10", "06-12", "11-04", "12-30", "12-31"],
    2025: ["01-01", "01-02", "01-03", "01-06", "01-07", "01-08", "05-01", "05-02", "05-08", "05-09", "06-12",
           "06-13", "11-03", "11-04", "12-31"],
    2026: ["01-01", "01-02", "01-05", "01-06", "01-07", "01-08", "01-09", "02-23", "03-09", "05-01", "05-11",
           "06-12", "11-04", "12-31"],
}
_WORKING_WEEKENDS = {2024: ["04-27", "11-02", "12-28"], 2025: ["11-01"], 2026: []}
HOLIDAYS = {date.fromisoformat(f"{y}-{md}") for y, l in _HOLIDAYS.items() for md in l}
WORKING_WEEKENDS = {date.fromisoformat(f"{y}-{md}") for y, l in _WORKING_WEEKENDS.items() for md in l}


def is_bd(d: date) -> bool:
    if d in WORKING_WEEKENDS:
        return True
    return d.weekday() < 5 and d not in HOLIDAYS


def next_bd(d: date) -> date:
    while not is_bd(d):
        d += timedelta(days=1)
    return d


def prev_bd(d: date) -> date:
    while not is_bd(d):
        d -= timedelta(days=1)
    return d


def add_bd(d: date, n: int) -> date:
    d = next_bd(d)
    for _ in range(n):
        d = next_bd(d + timedelta(days=1))
    return d


def mday(y: int, m: int, d: int) -> date:
    return date(y, m, min(d, calendar.monthrange(y, m)[1]))


def month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def add_months(y: int, m: int, k: int) -> tuple[int, int]:
    t = y * 12 + (m - 1) + k
    return t // 12, t % 12 + 1


MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь",
          "ноябрь", "декабрь"]


def money(x: float) -> str:
    s = f"{x:,.2f}".replace(",", " ").replace(".", ",")
    return s


def dmy(d: date) -> str:
    return d.strftime("%d.%m.%Y")


@dataclass(frozen=True)
class Party:
    name: str
    inn: str


def fake_inn(name: str, person: bool = False) -> str:
    h = hashlib.sha256(name.encode("utf-8")).hexdigest()
    digits = "".join(str(int(c, 16) % 10) for c in h)
    return "00" + digits[:(12 if person else 10) - 2]


def P(name: str, person: bool = False, inn: str | None = None) -> Party:
    return Party(name, inn if inn is not None else fake_inn(name, person))


BANK = Party("ПАО «Банк»", "0068275202")
FNS = Party("Казначейство России (ФНС России)", "7727406020")
NO_PERSON = Party("Физическое лицо", "")
OTHER_BANK = "АО «Банк-2»"


@dataclass
class Op:
    date: date
    direction: str
    amount: float
    party: Party
    purpose: str
    kind: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


ENP_VARIANTS = ["Единый налоговый платеж", "ЕНП", "Единый налоговый платёж", "Уплата ЕНП",
                "Перечисление единого налогового платежа", "ЕДИНЫЙ НАЛОГОВЫЙ ПЛАТЕЖ", "Пополнение ЕНС"]


class Book:
    def __init__(self, cid: str, name: str, inn: str, legal_form: str, industry: str, start: date, end: date,
                 rng: np.random.Generator, regime: str, future_days: int = 45):
        self.cid, self.name, self.inn, self.legal_form, self.industry = cid, name, inn, legal_form, industry
        self.start, self.end = start, end
        self.fut_end = end + timedelta(days=future_days)
        self.rng = rng
        self.regime = regime
        self.me = Party(name, inn)
        self.ops: list[Op] = []
        self.revenue_by_q: dict[tuple[int, int], float] = {}
        self.expense_by_q: dict[tuple[int, int], float] = {}
        self.input_vat_by_q: dict[tuple[int, int], float] = {}
        self.payroll_by_m: dict[tuple[int, int], float] = {}
        self.policy: list[tuple[date, Any, str]] = []
        self.target_end: float | None = None
        self.start_balance = 0.0
        self.notes: list[str] = []

    def add(self, d: date, direction: str, amount: float, party: Party, purpose: str, kind: str = "",
            shift: str = "forward", meta: dict[str, Any] | None = None, revenue: bool = False,
            expense: bool = False, vat_in: float = 0.0) -> Op | None:
        if shift == "forward":
            d = next_bd(d)
        elif shift == "backward":
            d = prev_bd(d)
        if d < self.start or d > self.fut_end:
            return None
        amount = round(float(amount), 2)
        if amount <= 0:
            return None
        op = Op(d, direction, amount, party, purpose, kind, meta or {})
        self.ops.append(op)
        q = (d.year, (d.month - 1) // 3 + 1)
        if revenue:
            self.revenue_by_q[q] = self.revenue_by_q.get(q, 0.0) + amount
        if expense:
            self.expense_by_q[q] = self.expense_by_q.get(q, 0.0) + amount
        if vat_in:
            self.input_vat_by_q[q] = self.input_vat_by_q.get(q, 0.0) + vat_in
        return op

    def noise(self, sigma: float) -> float:
        return float(np.exp(sigma * self.rng.standard_normal() - 0.5 * sigma ** 2))

    def vat_text(self, amount: float, d: date) -> str:
        rate = vat_rate(self.regime, d)
        if not rate:
            return "НДС не облагается"
        return f"в т.ч. НДС ({rate}%) {money(amount * rate / (100 + rate))}"

    def monthly(self, day: int, direction: str, amount: Callable[[int, int], float], party: Party,
                purpose: Callable[[int, int], str], kind: str, shift: str = "forward", expense: bool = True,
                start: date | None = None, until: date | None = None, vat: bool = False) -> None:
        for y, m in month_iter(start or self.start, until or self.fut_end):
            a = amount(y, m)
            d = mday(y, m, day)
            if (start and d < start) or (until and d > until):
                continue
            vin = a * 20 / 120 if vat else 0.0
            self.add(d, direction, a, party, purpose(y, m), kind, shift, expense=expense, vat_in=vin)

    def payroll(self, fot: Callable[[int, int], float], advance_day: int = 25, salary_day: int = 10,
                advance_share: float = 0.4, employees: int = 10, bonus_month: float = 0.0) -> None:
        reg = 10 + int(self.rng.integers(0, 30))
        for y, m in month_iter(self.start, self.fut_end):
            total = fot(y, m) * self.noise(0.02)
            self.payroll_by_m[(y, m)] = total
            py, pm = add_months(y, m, -1)
            prev_total = self.payroll_by_m.get((py, pm), fot(py, pm))
            sd = mday(y, m, salary_day)
            reg += 1
            self.add(sd, "out", prev_total * (1 - advance_share), BANK,
                     f"Перечисление заработной платы (окончательный расчет) за {MONTHS[pm - 1]} {py} г. по реестру № {reg} "
                     f"от {dmy(prev_bd(sd))}. НДС не облагается", "payroll", "backward", expense=True,
                     meta={"payroll": {"kind": "Зарплата", "employees": employees, "registry": reg}})
            ad = mday(y, m, advance_day)
            reg += 1
            self.add(ad, "out", total * advance_share, BANK,
                     f"Перечисление заработной платы (аванс) за {MONTHS[m - 1]} {y} г. по реестру № {reg} "
                     f"от {dmy(prev_bd(ad))}. НДС не облагается",
                     "payroll", "backward", expense=True,
                     meta={"payroll": {"kind": "Аванс", "employees": employees, "registry": reg}})
            if m == 12 and bonus_month:
                self.add(mday(y, 12, 26), "out", total * bonus_month, BANK,
                         f"Перечисление премии по итогам {y} г. по реестру №{reg + 1}. НДС не облагается",
                         "payroll", "backward", expense=True,
                         meta={"payroll": {"kind": "Премия", "employees": employees, "registry": reg + 1}})

    def taxes(self, contributions_k: float = 0.40, usn_reduction: float = 0.5, fixed_ip: bool = False,
              profit_margin: float = 0.08) -> None:
        for y, m in month_iter(self.start, self.fut_end):
            py, pm = add_months(y, m, -1)
            base = self.payroll_by_m.get((py, pm), 0.0) * contributions_k
            parts: list[str] = []
            extra = 0.0
            if self.regime.startswith("usn") and m in (4, 7, 10):
                rev = self.revenue_by_q.get((y, (m - 4) // 3 + 1), 0.0)
                tax = self._usn_tax(rev, (y, (m - 4) // 3 + 1), usn_reduction, base * 3)
                if tax > 0:
                    extra += tax
                    parts.append(f"аванс по УСН за {['', '1 квартал', 'полугодие', '9 месяцев'][(m - 1) // 3]} {y} г.")
            annual_month = 4 if self.legal_form == "ИП" else 3
            if self.regime.startswith("usn") and m == annual_month:
                rev = self.revenue_by_q.get((y - 1, 4), 0.0)
                tax = self._usn_tax(rev, (y - 1, 4), usn_reduction, base * 3)
                if tax > 0:
                    extra += tax
                    parts.append(f"УСН за {y - 1} г.")
            vq = (y - 1, 4) if m <= 3 else (y, (m - 1) // 3)
            rate = vat_rate(self.regime, date(vq[0], vq[1] * 3, 1))
            if rate:
                rev = self.revenue_by_q.get(vq, 0.0)
                out_vat = rev * rate / (100 + rate)
                in_vat = self.input_vat_by_q.get(vq, 0.0) if rate >= 20 else 0.0
                vat = max(0.0, out_vat - in_vat) / 3
                if vat > 0:
                    extra += vat
                    parts.append(f"НДС за {vq[1]} кв. {vq[0]} г. (1/3)")
            if self.regime == "osno" and m in (3, 4, 7, 10):
                pq = (y - 1, 4) if m == 3 else (y, (m - 1) // 3)
                rev = self.revenue_by_q.get(pq, 0.0) / (1 + vat_rate("osno", date(pq[0], pq[1] * 3, 1)) / 100)
                tax = rev * profit_margin * (0.20 if pq[0] < 2025 else 0.25)
                extra += tax
                parts.append("налог на прибыль" + (" за год" if m == 3 else " (аванс)"))
            if fixed_ip and m in (3, 6, 9, 12):
                fixed = (49_500 if y < 2025 else 53_658 if y == 2025 else 57_390) / 4
                extra += fixed
                parts.append("фиксированные страховые взносы ИП")
            amount = base + extra
            if amount <= 0:
                continue
            purpose = self.rng.choice(ENP_VARIANTS)
            if self.rng.random() < 0.55:
                purpose += f" за {MONTHS[pm - 1]} {py} г."
            if self.rng.random() < 0.3:
                purpose += " КБК 18201061201010000510"
            self.add(mday(y, m, 28), "out", amount * self.noise(0.015), FNS, purpose, "tax", "forward",
                     meta={"tax": {"base": round(base, 2), "extra": round(extra, 2), "parts": parts}})

    def _usn_tax(self, rev: float, q: tuple[int, int], reduction: float, contributions: float) -> float:
        if self.regime.startswith("usn6"):
            tax = rev * 0.06
            return max(tax - min(contributions, tax * reduction), 0.0)
        exp = self.expense_by_q.get(q, 0.0)
        return max((rev - exp) * 0.15, rev * 0.01 / 4)

    def withdraw_policy(self, dates_keep: list[tuple[date, Any]], party: Party, purpose: str) -> None:
        for d, keep in dates_keep:
            self.policy.append((next_bd(d), keep, purpose))
        self._policy_party = party

    def finalize(self) -> list[Op]:
        self.ops.sort(key=lambda o: (o.date, 0 if o.direction == "in" else 1))
        net_by_day: dict[date, float] = {}
        for o in self.ops:
            net_by_day[o.date] = net_by_day.get(o.date, 0.0) + (o.amount if o.direction == "in" else -o.amount)
        pol = sorted(self.policy, key=lambda x: x[0])
        for i, (pd_, keep, purpose) in enumerate(pol):
            bal_before = self.start_balance + sum(v for d, v in net_by_day.items() if d < pd_)
            if keep == "auto":
                if self.target_end is None:
                    continue
                after = sum(v for d, v in net_by_day.items() if pd_ <= d <= self.end)
                keep_v = self.target_end - after
            else:
                keep_v = float(keep)
            amt = math.floor(max(0.0, bal_before - keep_v) / 10_000) * 10_000
            if amt > 0:
                self.ops.append(Op(pd_, "out", float(amt), self._policy_party, purpose, "owner"))
                net_by_day[pd_] = net_by_day.get(pd_, 0.0) - amt
        self.ops.sort(key=lambda o: (o.date, 0 if o.direction == "in" else 1))
        return self.ops


def vat_rate(regime: str, d: date) -> int:
    if regime == "osno":
        return 22 if d.year >= 2026 else 20
    if regime.endswith("_vat5"):
        return 5 if d.year >= 2026 else 0
    return 0


def season(table: dict[int, float], d: date) -> float:
    return table.get(d.month, 1.0)


def growth(d: date, start: date, rate: float) -> float:
    return (1 + rate) ** ((d - start).days / 365.0)


def every_day(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def weekly(start: date, end: date, weekday: int):
    d = start + timedelta(days=(weekday - start.weekday()) % 7)
    while d <= end:
        yield d
        d += timedelta(days=7)


def acquiring(b: Book, sales: Callable[[date], float], share: float, fee: float = 0.018, sbp: float = 0.0,
              cash: float = 0.0) -> None:
    cash_acc = 0.0
    for d in every_day(b.start - timedelta(days=3), b.fut_end):
        s = sales(d)
        if s <= 0:
            continue
        credit = next_bd(d + timedelta(days=1))
        a = s * share * (1 - fee)
        b.add(credit, "in", a, BANK,
              f"Зачисление средств по операциям эквайринга за {dmy(d)}. Комиссия {money(s * share * fee)}. "
              f"НДС не облагается", "revenue", "none", revenue=True)
        if sbp:
            b.add(credit, "in", s * sbp * 0.993, BANK, f"Зачисление по операциям СБП (QR-код) за {dmy(d)}. Без НДС",
                  "revenue", "none", revenue=True)
        cash_acc += s * cash
        if cash and d.weekday() in (0, 3) and is_bd(d):
            b.add(d, "in", round(cash_acc, -2), b.me, "Взнос наличных через устройство самообслуживания (выручка)",
                  "revenue", "none", revenue=True)
            cash_acc = 0.0


def supplier_weekly(b: Book, party: Party, weekday: int, amount: Callable[[date], float], purpose: str,
                    vat: bool = True, kind: str = "suppliers") -> None:
    n = 100 + int(b.rng.integers(0, 400))
    for d in weekly(b.start, b.fut_end, weekday):
        n += 1
        a = amount(d)
        b.add(d, "out", a, party, f"Оплата по счету №{n} от {dmy(d - timedelta(days=2))} за {purpose}. "
              + ("в т.ч. НДС (20%) " + money(a / 6) if vat else "НДС не облагается"), kind,
              expense=True, vat_in=a / 6 if vat else 0.0)


def add_dirt(rows: list[dict[str, Any]], rng: np.random.Generator, dup: int, empty_purpose: float,
             empty_inn: float, gap: tuple[date, int] | None, protect: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        r = dict(r)
        if not protect(r):
            if rng.random() < empty_purpose:
                r["purpose"] = ""
            if r["counterparty_inn"] and rng.random() < empty_inn:
                r["counterparty_inn"] = ""
        out.append(r)
    if gap:
        g0 = gap[0]
        days, d = set(), next_bd(g0)
        while len(days) < gap[1]:
            days.add(d)
            d = next_bd(d + timedelta(days=1))
        out = [r for r in out if r["date"] not in days]
    cand = [i for i, r in enumerate(out) if not protect(r)]
    for i in sorted(rng.choice(cand, size=min(dup, len(cand)), replace=False), reverse=True):
        out.insert(i + 1, dict(out[i]))
    return out


def gen_coffee(b: Book) -> None:
    sz = {1: 0.78, 2: 0.9, 3: 0.98, 4: 1.0, 5: 1.08, 6: 1.12, 7: 1.1, 8: 1.07, 9: 1.0, 10: 0.98, 11: 0.96, 12: 1.17}
    wk = [1.0, 0.96, 0.98, 1.0, 1.12, 1.32, 1.22]
    special = {(2, 14): 1.3, (3, 8): 1.45, (12, 31): 0.6, (1, 1): 0.3, (9, 1): 1.15}

    def sales(d: date) -> float:
        base = 47_000 * wk[d.weekday()] * season(sz, d) * growth(d, b.start, 0.07) * special.get((d.month, d.day), 1.0)
        return base * b.noise(0.13)

    acquiring(b, sales, share=0.82, fee=0.017, sbp=0.07, cash=0.11)

    roaster = P("ООО «Обжарочный цех Арабика»")
    dairy = P("ООО «Молочный двор»")
    bakery = P("ИП Хлебников С.А.", person=True)
    supplier_weekly(b, roaster, 1, lambda d: 0.075 * 7 * 47_000 * season(sz, d) * growth(d, b.start, 0.09) * b.noise(0.12),
                    "кофе зерновой", vat=True)
    supplier_weekly(b, dairy, 0, lambda d: 0.03 * 7 * 47_000 * season(sz, d) * b.noise(0.1), "молочную продукцию")
    supplier_weekly(b, dairy, 3, lambda d: 0.028 * 7 * 47_000 * season(sz, d) * b.noise(0.1), "молочную продукцию")
    for wd in (0, 2, 4):
        supplier_weekly(b, bakery, wd, lambda d: 0.017 * 7 * 47_000 * season(sz, d) * b.noise(0.15), "выпечку",
                        vat=False)
    pack = P("ООО «ЭкоУпак»")
    b.monthly(12, "out", lambda y, m: 26_000 * b.noise(0.2), pack,
              lambda y, m: f"Оплата за упаковку и стаканы по счету №{m * 7 + y % 10}. в т.ч. НДС 20%", "suppliers", vat=True)

    landlord = P("ООО «Торговый дом Садовый»")
    b.monthly(1, "out", lambda y, m: 175_000 if (y, m) < (2026, 1) else 189_000, landlord,
              lambda y, m: f"Арендная плата за {MONTHS[m - 1]} {y} г. по договору аренды №14-А от 01.09.2023. НДС не облагается",
              "rent")
    b.monthly(15, "out", lambda y, m: (34_000 if m in (11, 12, 1, 2) else 26_000) * b.noise(0.08), P("АО «Донэнергосбыт»"),
              lambda y, m: f"Оплата электроэнергии по договору №61070{y % 100} за {MONTHS[(m - 2) % 12]}. в т.ч. НДС 20%", "utilities")
    b.monthly(18, "out", lambda y, m: 5_800 * b.noise(0.1), P("АО «Водоканал»"),
              lambda y, m: "Оплата за водоснабжение и водоотведение. в т.ч. НДС 20%", "utilities")
    b.monthly(5, "out", lambda y, m: 2_490, P("ООО «Связь-Онлайн»"), lambda y, m: "Оплата услуг связи и интернета. в т.ч. НДС 20%", "utilities")
    b.monthly(7, "out", lambda y, m: 5_200, P("ООО «Ресторанные системы»"),
              lambda y, m: f"Лицензия на ПО учета ресторана за {MONTHS[m - 1]}. НДС не облагается", "utilities")
    b.monthly(20, "out", lambda y, m: 6_000, P("ООО «ЧОП Щит»"), lambda y, m: "Оплата услуг охраны по договору №33. Без НДС", "utilities")
    lease = P("ООО «Лизинг-Оборудование»")
    b.monthly(15, "out", lambda y, m: 41_800, lease,
              lambda y, m: "Лизинговый платеж по договору №ЛО-2023/118 (кофемашина). в т.ч. НДС 20%", "loans",
              until=date(2026, 6, 30))
    b.monthly(31, "out", lambda y, m: 1_490, BANK, lambda y, m: f"Комиссия за ведение счета за {MONTHS[m - 1]} {y} г.",
              "bank_fees", shift="backward")

    b.payroll(lambda y, m: 390_000 * growth(date(y, m, 1), b.start, 0.1), advance_day=25, salary_day=10, employees=9)
    b.taxes(contributions_k=0.40, usn_reduction=0.5)

    b.add(date(2025, 6, 16), "out", 400_000, b.me, f"Перевод собственных средств на расчетный счет в {OTHER_BANK}. НДС не облагается", "transfers")
    b.add(date(2025, 7, 14), "in", 400_000, b.me, f"Перевод собственных средств с расчетного счета в {OTHER_BANK}. НДС не облагается", "transfers")
    b.add(date(2025, 3, 11), "out", 61_250.40, roaster, "Оплата по счету №388 от 07.03.2025 за кофе зерновой. в т.ч. НДС (20%) 10 208,40", "suppliers")
    b.add(date(2025, 3, 14), "in", 61_250.40, roaster, "Возврат ошибочно перечисленных денежных средств (повторная оплата счета №388)", "refund")
    b.withdraw_policy([(date(y, m, 15), 650_000) for y, m in month_iter(b.start, b.end) if m in (3, 6, 9, 12)]
                      + [(date(2026, 9, 21), "auto")],
                      P("Участник ООО (физ. лицо)", person=True), "Выплата дивидендов участнику по решению №{n}. НДФЛ удержан")
    b.start_balance = 520_000
    b.target_end = 610_000


ANCHOR = P("АО «ДонТрансЛогистика»")


def gen_b2b(b: Book) -> None:
    clients = [
        (ANCHOR, 2_050_000, 15, 0.06, b.start, "Д-17/2023"),
        (P("ООО «Агро-Юг Трейд»"), 980_000, 7, 0.05, b.start, "Д-04/2024"),
        (P("ООО «МедЦентр Здоровье»"), 540_000, 3, 0.04, b.start, "Д-21/2024"),
        (P("ООО «Северный ритейл»"), 320_000, 10, 0.0, date(2026, 3, 1), "Д-08/2026"),
    ]
    inv_no = 180
    for party, base, deferral, g, since, contract in clients:
        for y, m in month_iter(since - timedelta(days=31) if since <= b.start else since, b.fut_end):
            issued = add_bd(date(y, m, 1), 0)
            sy, sm = add_months(y, m, -1)
            if date(sy, sm, 1) < (since - timedelta(days=62) if since <= b.start else since):
                continue
            inv_no += 1
            vat = vat_rate("osno", date(sy, sm, 1))
            amount = round(base * growth(date(sy, sm, 1), b.start, g) * (1.22 / 1.2 if vat == 22 else 1.0), -3)
            due = add_bd(issued, deferral)
            late = 0
            r = b.rng.random()
            if party is ANCHOR:
                late = int(b.rng.integers(0, 3)) if r < 0.75 else int(b.rng.integers(3, 7))
                if (sy, sm) == (2025, 12):
                    late = 13
                if (sy, sm) == (2026, 9):
                    late = None
            else:
                late = 0 if r < 0.8 else int(b.rng.integers(1, 5))
            meta = {"invoice": {"number": str(inv_no), "issued": issued.isoformat(), "due": due.isoformat(),
                                "amount": amount, "contract": contract, "period": f"{MONTHS[sm - 1]} {sy}"}}
            if late is None:
                paid_on = date(2026, 11, 16)
            else:
                paid_on = add_bd(due, late)
            purpose = (f"Оплата по счету №{inv_no} от {dmy(issued)} за услуги ИТ-сопровождения за {MONTHS[sm - 1]} {sy} г. "
                       f"по договору №{contract}. в т.ч. НДС ({vat}%) {money(amount * vat / (100 + vat))}")
            op = b.add(paid_on, "in", amount, party, purpose, "revenue", "forward", meta=meta, revenue=True)
            if op is None and next_bd(paid_on) > b.fut_end and issued <= b.fut_end:
                b.notes.append(json.dumps({"open_invoice": {**meta["invoice"], "client": party.name, "inn": party.inn}},
                                          ensure_ascii=False))
    small = [P(n) for n in ("ООО «Альфа-Строй»", "ООО «ТехноПарк Дон»", "ООО «Гранд Отель»", "ООО «Кондитер Юг»",
                            "ООО «Фармация Плюс»", "ООО «Лидер Авто»", "ИП Гончаров П.В.", "ООО «Эко Ферма»")]
    small[6] = P("ИП Гончаров П.В.", person=True)
    for y, m in month_iter(b.start, b.fut_end):
        for _ in range(int(b.rng.integers(2, 6))):
            party = small[int(b.rng.integers(0, len(small)))]
            d = date(y, m, int(b.rng.integers(1, calendar.monthrange(y, m)[1] + 1)))
            amount = round(float(b.rng.choice([45_000, 60_000, 85_000, 120_000, 150_000, 210_000])) * b.noise(0.1), -2)
            inv_no += 1
            issued = prev_bd(d - timedelta(days=int(b.rng.integers(5, 15))))
            b.add(d, "in", amount, party,
                  f"Оплата по счету №{inv_no} от {dmy(issued)} за работы по настройке ПО. {b.vat_text(amount, d)}",
                  "revenue", meta={"invoice": {"number": str(inv_no), "issued": issued.isoformat(),
                                               "due": next_bd(d).isoformat(), "amount": amount,
                                               "period": "разовые работы"}},
                  revenue=True)

    b.payroll(lambda y, m: 1_380_000 * (1.08 if y >= 2025 else 1.0) * (1.07 if y >= 2026 else 1.0),
              advance_day=20, salary_day=5, employees=22, bonus_month=0.35)
    office = P("ООО «Бизнес-центр Кристалл»")

    def office_rent(y: int, m: int) -> float:
        return 380_000.0 if y < 2026 else 399_000.0

    b.monthly(1, "out", office_rent, office,
              lambda y, m: f"Арендная плата за {MONTHS[m - 1]} {y} г. по договору №БЦ-112 от 15.01.2023. "
                           f"{b.vat_text(office_rent(y, m), date(y, m, 1))}",
              "rent", vat=True)
    subs = [(P("ООО «КодМастер»"), 210_000, 7), (P("ООО «Сеть-Сервис»"), 145_000, 9)]
    for party, amt, day in subs:
        b.monthly(day, "out", lambda y, m, amt=amt: amt * b.noise(0.06), party,
                  lambda y, m: f"Оплата по договору субподряда за {MONTHS[(m - 2) % 12]} по акту. в т.ч. НДС 20%",
                  "suppliers", vat=True)
    b.monthly(3, "out", lambda y, m: 118_000 * b.noise(0.03), P("ООО «Софт Лицензии»"),
              lambda y, m: f"Оплата подписки на ПО (лицензии) за {MONTHS[m - 1]}. НДС не облагается", "utilities")
    b.monthly(5, "out", lambda y, m: 76_000 * growth(date(y, m, 1), b.start, 0.1), P("ООО «ОблакоТех»"),
              lambda y, m: f"Оплата облачных серверов за {MONTHS[m - 1]} {y} г. (предоплата). в т.ч. НДС 20%", "utilities", vat=True)
    b.monthly(10, "out", lambda y, m: 14_200, P("ПАО «Связь-Телеком»"), lambda y, m: "Оплата услуг связи по договору №700-118. в т.ч. НДС 20%", "utilities")
    b.monthly(15, "out", lambda y, m: 58_400, P("ООО «Лизинг-Авто»"),
              lambda y, m: "Лизинговый платеж по договору №ЛА-0456 (автомобиль). в т.ч. НДС 20%", "loans", vat=True)
    loan_start = date(2025, 3, 25)
    b.add(date(2025, 3, 3), "in", 1_200_000, BANK, "Выдача кредита по кредитному договору №КД-2025/0311 на пополнение оборотных средств", "loans")
    for y, m in month_iter(loan_start, b.fut_end):
        k = (y - 2025) * 12 + m - 3
        if k > 24:
            break
        b.add(mday(y, m, 25), "out", 57_900, BANK,
              f"Погашение кредита и процентов по кредитному договору №КД-2025/0311 (платеж {k} из 24)", "loans",
              meta={"loan": {"contract": "КД-2025/0311", "n": k, "of": 24}})
    b.monthly(28, "out", lambda y, m: 2_900, BANK, lambda y, m: f"Комиссия за ведение счета за {MONTHS[m - 1]} {y} г.",
              "bank_fees", shift="backward")
    misc = [P("ООО «Канцмир»"), P("ООО «Клининг Про»"), P("ООО «Такси Деловое»"), P("ООО «Учебный центр Профи»")]
    for y, m in month_iter(b.start, b.fut_end):
        for _ in range(int(b.rng.integers(2, 5))):
            d = date(y, m, int(b.rng.integers(1, calendar.monthrange(y, m)[1] + 1)))
            party = misc[int(b.rng.integers(0, len(misc)))]
            a = round(float(b.rng.uniform(6_000, 48_000)), 2)
            b.add(d, "out", a, party, f"Оплата по счету №{int(b.rng.integers(10, 999))}. в т.ч. НДС 20%", "other",
                  expense=True, vat_in=a / 6)
    b.add(date(2025, 7, 14), "out", 1_500_000, b.me, "Перевод собственных средств на депозитный счет. НДС не облагается", "transfers")
    b.add(date(2025, 10, 14), "in", 1_517_800, b.me, "Возврат депозита и выплата процентов по депозитному договору №ДП-77", "transfers")
    b.add(date(2026, 4, 7), "in", 96_000, P("ООО «Альфа-Сервис Плюс»"), "Оплата по счету №1043 за услуги", "other")
    b.add(date(2026, 4, 9), "out", 96_000, P("ООО «Альфа-Сервис Плюс»"),
          "Возврат ошибочно зачисленных денежных средств по п/п №1043 от 07.04.2026. НДС не облагается", "refund")

    b.taxes(contributions_k=0.38, profit_margin=0.09)
    owner = P("Участник ООО (физ. лицо)", person=True)
    keep = [(date(y, m, 18), 2_600_000) for y, m in month_iter(b.start, b.end) if m in (2, 5, 8, 11)]
    keep += [(date(2025, 12, 22), 1_350_000), (date(2026, 9, 14), "auto")]
    b.withdraw_policy(keep, owner, "Выплата дивидендов участнику по решению №{n}. НДФЛ удержан")
    b.start_balance = 2_300_000
    b.target_end = 2_520_000


def gen_construction(b: Book) -> None:
    clients = [P("ООО «СЗ Донской квартал»"), P("ООО «ГК Новострой»"), P("ООО «Логистик Парк Юг»"),
               P("МКУ «Управление капитального строительства»"), P("ООО «Агрохолдинг Степь»")]
    mat = [P("ООО «БетонСнаб»"), P("ООО «МеталлТорг Юг»"), P("ООО «СтройБаза Дон»")]
    sub = P("ООО «ЭлектроМонтаж»")
    projects = []
    rng = b.rng
    n = 1
    per_month = {1: 0, 2: 1, 3: 2, 4: 2, 5: 2, 6: 2, 7: 2, 8: 2, 9: 1, 10: 1, 11: 1, 12: 0}
    for y, m in month_iter(b.start - timedelta(days=75), b.fut_end - timedelta(days=20)):
        k = per_month[m] if (y, m) not in ((2025, 12), (2026, 1), (2026, 2)) else 0
        if (y, m) == (2026, 2):
            k = 0
        for j in range(k):
            signed = add_bd(date(y, m, 3 + 12 * j), int(rng.integers(0, 6)))
            value = round(4.1e6 * growth(signed, b.start, 0.16) * b.noise(0.2), -4)
            client = clients[int(rng.integers(0, len(clients)))]
            if client is clients[3]:
                client = clients[0]
            projects.append((n, signed, value, int(rng.integers(2, 4)), client))
            n += 1
    projects.append((90, date(2025, 10, 6), 7.2e6, 3, clients[3]))
    for num, signed, value, months_, client in projects:
        contract = f"{num:02d}/{signed.year % 100}-СМР"
        prepay = 0.3 if client is not clients[3] else 0.0
        retention = 0.1
        sched = []
        if prepay:
            sched.append((add_bd(signed, 3), value * prepay, "аванс"))
        stage_val = value * (1 - prepay - retention) / months_
        for k in range(1, months_ + 1):
            sy, sm = add_months(signed.year, signed.month, k)
            sched.append((add_bd(mday(sy, sm, 10), int(rng.integers(5, 20))), stage_val, f"акт КС-2 №{k}"))
        ey, em = add_months(signed.year, signed.month, months_)
        final = add_bd(mday(ey, em, 15), int(rng.integers(20, 45)))
        if num == 90:
            final = date(2026, 3, 16)
        sched.append((final, value * retention, "гарантийное удержание"))
        for when, amount, what in sched:
            vat = vat_rate(b.regime, when)
            purpose = (f"Оплата по договору подряда №{contract} от {dmy(signed)}, {what}. "
                       + (f"в т.ч. НДС ({vat}%) {money(amount * vat / (100 + vat))}" if vat else "НДС не облагается"))
            if client is clients[3]:
                purpose = f"Оплата по муниципальному контракту №{contract} (44-ФЗ), {what}. НДС не облагается"
            b.add(when, "in", round(amount, -2), client, purpose, "revenue",
                  meta={"contract": {"number": contract, "signed": signed.isoformat(), "value": value,
                                     "client": client.name, "inn": client.inn, "prepay": prepay,
                                     "stage": what, "planned": when.isoformat()}}, revenue=True)
            if what != "гарантийное удержание":
                m_party = mat[int(rng.integers(0, len(mat)))]
                ma = amount * 0.42 * b.noise(0.1)
                md = when - timedelta(days=int(rng.integers(5, 25)))
                b.add(md, "out", ma, m_party, f"Оплата за строительные материалы по счету №{int(rng.integers(100, 9999))}. в т.ч. НДС (20%) {money(ma / 6)}",
                      "suppliers", expense=True, vat_in=ma / 6)
            if what.startswith("акт") and rng.random() < 0.5:
                sa = amount * 0.12
                b.add(when + timedelta(days=int(rng.integers(2, 10))), "out", sa, sub,
                      f"Оплата по договору субподряда к договору №{contract}. в т.ч. НДС (20%) {money(sa / 6)}",
                      "suppliers", expense=True, vat_in=sa / 6)
    b.add(date(2026, 2, 10), "out", 1_380_000, mat[1], "Предоплата 50% за металлопрокат по счету №2214 от 06.02.2026. в т.ч. НДС (20%) 230 000,00",
          "suppliers", expense=True, vat_in=230_000)
    sz_staff = {1: 0.7, 2: 0.7, 3: 0.85, 11: 0.85, 12: 0.75}
    b.payroll(lambda y, m: 1_080_000 * sz_staff.get(m, 1.0) * (1.07 if y >= 2026 else 1.0), advance_day=25,
              salary_day=10, employees=17)
    fuel = P("ООО «Топливные карты Юг»")
    supplier_weekly(b, fuel, 1, lambda d: (62_000 if d.month in range(4, 11) else 28_000) * b.noise(0.15),
                    "топливо по топливным картам")
    rent_t = P("ООО «СпецТехАренда»")
    supplier_weekly(b, rent_t, 3, lambda d: (85_000 if d.month in range(4, 11) else 0.0) * b.noise(0.2),
                    "аренду спецтехники с экипажем")
    b.monthly(5, "out", lambda y, m: 120_000, P("ИП Сидоренко В.Н.", person=True),
              lambda y, m: f"Арендная плата за производственную базу за {MONTHS[m - 1]} {y} г. НДС не облагается", "rent")
    b.monthly(20, "out", lambda y, m: 186_300, P("АО «ЛизингТехника»"),
              lambda y, m: "Лизинговый платеж по договору №ЛТ-2023/0912 (экскаватор). в т.ч. НДС 20%", "loans", vat=True)
    for y, m in month_iter(b.start, b.fut_end):
        b.add(mday(y, m, 12), "out", 245_000, BANK,
              "Погашение основного долга и процентов по кредитному договору №КД-2024/0187 от 12.03.2024", "loans",
              meta={"loan": {"contract": "КД-2024/0187"}})
    b.monthly(16, "out", lambda y, m: (31_000 if m in (12, 1, 2) else 18_000) * b.noise(0.1), P("АО «Донэнергосбыт»"),
              lambda y, m: "Оплата электроэнергии (производственная база). в т.ч. НДС 20%", "utilities")
    b.monthly(30, "out", lambda y, m: 2_490, BANK, lambda y, m: f"Комиссия за ведение счета за {MONTHS[m - 1]} {y} г.",
              "bank_fees", shift="backward")
    b.add(date(2026, 2, 26), "in", 1_200_000, P("Учредитель (физ. лицо)", person=True),
          "Поступление займа от учредителя по договору процентного займа №1 от 26.02.2026. НДС не облагается", "loans")
    b.add(date(2026, 8, 24), "out", 1_200_000, P("Учредитель (физ. лицо)", person=True),
          "Возврат займа учредителю по договору №1 от 26.02.2026. НДС не облагается", "loans")
    b.add(date(2026, 3, 18), "in", 3_000_000, BANK, "Выдача транша по кредитной линии №КЛ-2026/014 на пополнение оборотных средств", "loans")
    for d_, amt in ((date(2026, 7, 20), 1_528_000), (date(2026, 8, 20), 1_512_000)):
        b.add(d_, "out", amt, BANK, "Погашение транша и процентов по кредитной линии №КЛ-2026/014", "loans")
    b.add(date(2025, 8, 5), "out", 148_000, mat[0], "Оплата за бетон по счету №5521 от 01.08.2025. в т.ч. НДС (20%) 24 666,67", "suppliers")
    b.add(date(2025, 8, 8), "in", 148_000, mat[0], "Возврат ошибочно перечисленных средств по п/п №611 от 05.08.2025", "refund")
    b.taxes(contributions_k=0.40)
    owner = P("Учредитель (физ. лицо)", person=True)
    b.withdraw_policy([(date(y, m, 20), 4_200_000) for y, m in month_iter(b.start, b.end) if m in (6, 9, 11)]
                      + [(date(2026, 1, 26), 1_500_000), (date(2026, 9, 21), "auto")],
                      owner, "Выплата дивидендов участнику по решению №{n}. НДФЛ удержан")
    b.start_balance = 3_700_000
    b.target_end = 2_350_000


def gen_ecom(b: Book) -> None:
    sz = {1: 0.72, 2: 1.05, 3: 1.25, 4: 0.92, 5: 0.9, 6: 0.85, 7: 0.76, 8: 0.8, 9: 0.95, 10: 1.08, 11: 1.55, 12: 1.95}

    def sales(d: date) -> float:
        bf = 1.6 if (d.month == 11 and 8 <= d.day <= 12) or (d.month == 11 and 24 <= d.day <= 30) else 1.0
        return 104_000 * season(sz, d) * growth(d, b.start, 0.15) * bf * [1, 1, 1, 1, 0.95, 1.12, 1.18][d.weekday()] * b.noise(0.18)

    mp1, mp2 = P("ООО «Маркетплейс Альфа»"), P("ООО «Маркетплейс Бета»")
    rep = 3000
    for d in weekly(b.start, b.fut_end, 2):
        week = sum(sales(d - timedelta(days=k + 3)) for k in range(7)) * 0.62
        rep += 1
        b.add(d, "in", week * 0.74, mp1, f"Выплата по отчету о реализации №{rep} за период {dmy(d - timedelta(days=9))}–{dmy(d - timedelta(days=3))}. Без НДС",
              "revenue", revenue=True)
    for y, m in month_iter(b.start, b.fut_end):
        for day in (5, 20):
            d = mday(y, m, day)
            part = sum(sales(d - timedelta(days=k + 5)) for k in range(15)) * 0.25
            b.add(d, "in", part * 0.78, mp2, f"Перечисление денежных средств по агентскому договору №МБ-4471 за {dmy(d - timedelta(days=20))}–{dmy(d - timedelta(days=5))}. Без НДС",
                  "revenue", revenue=True)
    agg = P("ООО НКО «ПэйОнлайн»")
    for d in every_day(b.start, b.fut_end):
        s = sales(d) * 0.13
        b.add(next_bd(d + timedelta(days=1)), "in", s * 0.975, agg,
              f"Перевод денежных средств по операциям оплаты на сайте за {dmy(d)} (реестр). Без НДС", "revenue", "none", revenue=True)
    china = P("ООО «ВЭД-Импорт»")
    for y in range(b.start.year, b.fut_end.year + 1):
        big = 3.0e6 * growth(date(y, 8, 1), b.start, 0.12)
        b.add(date(y, 8, 12), "out", big * 0.3, china, f"Предоплата 30% по договору поставки №ВЭД-{y}/07 (товары к сезону). Без НДС", "suppliers", expense=True)
        b.add(date(y, 10, 6), "out", big * 0.7, china, f"Окончательный расчет 70% по договору поставки №ВЭД-{y}/07. Без НДС", "suppliers", expense=True)
        b.add(date(y, 2, 9), "out", big * 0.25, china, f"Оплата по договору поставки №ВЭД-{y}/02 (весенняя коллекция). Без НДС", "suppliers", expense=True)
    supplier_weekly(b, P("ООО «ТекстильОпт»"), 0, lambda d: 0.2 * 7 * 104_000 * season(sz, d) * growth(d, b.start, 0.15) * b.noise(0.2),
                    "товары для дома (текстиль)")
    supplier_weekly(b, P("ООО «Фулфилмент Про»"), 4, lambda d: 0.06 * 7 * 92_000 * season(sz, d) * b.noise(0.1),
                    "услуги фулфилмента")
    supplier_weekly(b, P("ООО «Реклама Онлайн»"), 1, lambda d: 0.05 * 7 * 92_000 * season(sz, d) * b.noise(0.15),
                    "продвижение в интернете", vat=True)
    b.monthly(3, "out", lambda y, m: 140_000, P("ООО «Склад-Сервис»"),
              lambda y, m: f"Арендная плата за склад за {MONTHS[m - 1]} {y} г. в т.ч. НДС 20%", "rent", vat=True)
    b.monthly(12, "out", lambda y, m: 34_000 * b.noise(0.15), P("ООО «ЭкоУпак»"),
              lambda y, m: "Оплата за упаковочные материалы. в т.ч. НДС 20%", "suppliers", vat=True)
    b.monthly(30, "out", lambda y, m: 1_990, BANK, lambda y, m: f"Комиссия за ведение счета за {MONTHS[m - 1]} {y} г.",
              "bank_fees", shift="backward")
    for d in every_day(b.start, b.fut_end):
        if is_bd(d) and b.rng.random() < 0.12:
            b.add(d, "out", round(float(b.rng.uniform(900, 7_500)), 2), NO_PERSON,
                  "Возврат денежных средств покупателю за возвращенный товар по заказу №" + str(int(b.rng.integers(10**5, 10**6))),
                  "refund")
    b.payroll(lambda y, m: 380_000 * growth(date(y, m, 1), b.start, 0.1), advance_day=25, salary_day=10, employees=6)
    b.taxes(contributions_k=0.40, usn_reduction=0.5)
    b.add(date(2025, 12, 22), "out", 900_000, b.me, f"Перевод собственных средств на счет в {OTHER_BANK}. НДС не облагается", "transfers")
    b.add(date(2026, 1, 19), "in", 900_000, b.me, f"Перевод собственных средств со счета в {OTHER_BANK}. НДС не облагается", "transfers")
    owner = P("Участник ООО (физ. лицо)", person=True)
    b.withdraw_policy([(date(y, 1, 26), 1_400_000) for y in (2025, 2026)] + [(date(2025, 6, 23), 1_500_000), (date(2026, 7, 20), "auto")],
                      owner, "Выплата дивидендов участнику по решению №{n}. НДФЛ удержан")
    b.start_balance = 1_900_000
    b.target_end = 1_650_000


def gen_studio(b: Book) -> None:
    sz = {1: 0.82, 2: 1.02, 3: 1.2, 4: 1.0, 5: 1.04, 6: 0.98, 7: 0.86, 8: 0.88, 9: 1.0, 10: 1.02, 11: 1.03, 12: 1.28}
    wk = [0.85, 0.92, 0.95, 1.0, 1.15, 1.3, 0.8]

    def sales(d: date) -> float:
        cert = 1.7 if (d.month, d.day) in ((3, 6), (3, 7), (12, 27), (12, 28), (2, 13)) else 1.0
        return 41_000 * wk[d.weekday()] * season(sz, d) * growth(d, b.start, 0.12) * cert * b.noise(0.16)

    acquiring(b, sales, share=0.7, fee=0.019)
    for d in every_day(b.start, b.fut_end):
        if not is_bd(d):
            continue
        for _ in range(int(b.rng.poisson(2.2))):
            b.add(d, "in", round(float(b.rng.choice([1_500, 2_200, 2_800, 3_500, 4_200, 5_000, 6_500])), -2), NO_PERSON,
                  "Перевод по СБП. Оплата услуг студии", "revenue", "none", revenue=True)
    masters = [P(n, person=True) for n in ("Самозанятый Орлова Е.В.", "Самозанятый Кравец Д.А.",
                                           "Самозанятый Нестерова Ю.И.", "Самозанятый Ахмедова Л.Р.")]
    for d in weekly(b.start, b.fut_end, 0):
        for mi, party in enumerate(masters):
            if mi == 3 and d < date(2025, 9, 1):
                continue
            a = 0.4 * 7 * 41_000 * season(sz, d) / 4.0 * b.noise(0.15)
            b.add(d, "out", a, party, f"Оплата по договору оказания услуг №{mi + 1}-СЗ, чек НПД №{int(b.rng.integers(10**8, 10**9))}. НДС не облагается",
                  "payroll", expense=True)
    supplier_weekly(b, P("ООО «ПрофКосметик»"), 2, lambda d: (0.09 * 7 * 41_000 * season(sz, d) * b.noise(0.2)) if d.isocalendar()[1] % 2 else 0,
                    "профессиональную косметику")
    b.monthly(1, "out", lambda y, m: 95_000 if y < 2026 else 102_000, P("ООО «Галерея Плаза»"),
              lambda y, m: f"Арендная плата за {MONTHS[m - 1]} {y} г. по договору №ГП-58. НДС не облагается", "rent")
    b.monthly(8, "out", lambda y, m: 25_000, P("ООО «Таргет Медиа»"), lambda y, m: "Оплата рекламных услуг по договору №ТМ-12. Без НДС", "other")
    b.monthly(14, "out", lambda y, m: 3_490, P("ООО «Онлайн-Запись»"), lambda y, m: "Подписка на сервис онлайн-записи клиентов. Без НДС", "utilities")
    b.monthly(17, "out", lambda y, m: 9_800 * b.noise(0.1), P("АО «Донэнергосбыт»"), lambda y, m: "Оплата электроэнергии. в т.ч. НДС 20%", "utilities")
    b.payroll(lambda y, m: 92_000, advance_day=25, salary_day=10, employees=2)
    b.taxes(contributions_k=0.40, usn_reduction=0.5, fixed_ip=True)
    for y, m in month_iter(b.start, b.fut_end):
        for day in (11, 26):
            b.add(mday(y, m, day), "out", round(float(b.rng.uniform(60_000, 120_000)), -3), b.me,
                  f"Перевод собственных средств на счет ИП в {OTHER_BANK}. НДС не облагается", "transfers")
    b.withdraw_policy([(date(2026, 9, 28), "auto")], b.me, f"Перевод собственных средств на счет ИП в {OTHER_BANK}. НДС не облагается")
    b.start_balance = 310_000
    b.target_end = 430_000


COMPANIES = [
    ("S01", "ООО «Кофейня Бодрое утро»", "ООО", "Общепит: кофейня (розница)", "usn6", 2.0, gen_coffee, 4, (date(2025, 2, 10), 4)),
    ("S02", "ООО «Вектор Бизнес-Сервис»", "ООО", "B2B-услуги: ИТ-аутсорсинг", "osno", 2.0, gen_b2b, 2, None),
    ("S03", "ООО «СтройМонтаж-Дон»", "ООО", "Строительство и монтаж", "usn15_vat5", 2.0, gen_construction, 3, None),
    ("S04", "ООО «Уютный дом онлайн»", "ООО", "Интернет-магазин (товары для дома)", "usn6_vat5", 1.75, gen_ecom, 5, (date(2025, 8, 18), 5)),
    ("S05", "ИП Ланская М.О. (студия красоты «Лаванда»)", "ИП", "Студия услуг (красота)", "usn6", 1.5, gen_studio, 3, None),
]


def build_company(spec: tuple, end: date, seed: int) -> tuple[Book, list[dict[str, Any]], list[dict[str, Any]]]:
    cid, name, form, industry, regime, years, gen, dup, gap = spec
    rng = np.random.default_rng([seed, int(cid[1:])])
    start = next_bd(end - timedelta(days=int(round(365.25 * years))))
    inn = fake_inn(name, person=(form == "ИП"))
    b = Book(cid, name, inn, form, industry, start, end, rng, regime)
    gen(b)
    ops = b.finalize()
    for k, o in enumerate(o for o in ops if o.kind == "owner"):
        o.purpose = o.purpose.replace("{n}", str(k + 1))
    bal = b.start_balance
    rows_hist, rows_fut = [], []
    by_day: dict[date, list[Op]] = {}
    for o in ops:
        by_day.setdefault(o.date, []).append(o)
    for d in sorted(by_day):
        day_ops = by_day[d]
        bal += sum(o.amount if o.direction == "in" else -o.amount for o in day_ops)
        for o in day_ops:
            r = {"date": d, "amount": o.amount, "direction": o.direction, "counterparty_inn": o.party.inn,
                 "counterparty_name": o.party.name, "purpose": o.purpose, "balance_eod": round(bal, 2),
                 "_kind": o.kind}
            (rows_hist if d <= end else rows_fut).append(r)
    protect = (lambda r: r["_kind"] in ("tax", "owner") or r["counterparty_name"] == ANCHOR.name) if cid == "S02" \
        else (lambda r: r["_kind"] in ("tax",))
    rows_hist = add_dirt(rows_hist, rng, dup, 0.025, 0.01, gap, protect)
    return b, rows_hist, rows_fut


def write_statement(path: Path, cid: str, rows: list[dict[str, Any]], fmt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig" if fmt == "raw" else "utf-8", newline="") as f:
        if fmt == "raw":
            w = csv.writer(f, delimiter=";")
            w.writerow(["company_id", "operation_id", "operation_date", "amount", "direction", "counterparty_inn",
                        "counterparty_name", "payment_purpose", "balance_eod"])
            for i, r in enumerate(rows, 1):
                w.writerow([cid, f"{cid}-{i:06d}", r["date"].isoformat(), f"{r['amount']:.2f}",
                            "Поступление" if r["direction"] == "in" else "Списание", r["counterparty_inn"],
                            r["counterparty_name"], r["purpose"], f"{r['balance_eod']:.2f}"])
        else:
            w = csv.writer(f, delimiter=",")
            w.writerow(["date", "amount", "direction", "counterparty_name", "counterparty_inn", "purpose", "balance_eod"])
            for r in rows:
                w.writerow([r["date"].isoformat(), f"{r['amount']:.2f}", r["direction"], r["counterparty_name"],
                            r["counterparty_inn"], r["purpose"], f"{r['balance_eod']:.2f}"])


def integrations_for(b: Book, end: date) -> dict[str, Any]:
    out: dict[str, Any] = {}
    window_past = end - timedelta(days=56)
    horizon = end + timedelta(days=45)
    org = {"Наименование": b.name, "ИНН": b.inn}

    sales_inv, supp_inv = [], []
    for o in b.ops:
        inv = o.meta.get("invoice")
        if inv and o.direction == "in":
            issued = date.fromisoformat(inv["issued"])
            if window_past <= issued <= end or (issued <= end < o.date):
                paid = o.date <= end
                sales_inv.append({"Номер": inv["number"], "Дата": inv["issued"], "Контрагент": {"Наименование": o.party.name, "ИНН": o.party.inn},
                                  "Сумма": inv["amount"], "СрокОплаты": inv["due"], "Договор": inv.get("contract"),
                                  "Оплачен": paid, "СуммаОплаты": inv["amount"] if paid else 0.0,
                                  "ДатаОплаты": o.date.isoformat() if paid else None,
                                  "Комментарий": f"Услуги за {inv['period']}"})
    for n in b.notes:
        j = json.loads(n).get("open_invoice")
        if j and date.fromisoformat(j["issued"]) <= end:
            sales_inv.append({"Номер": j["number"], "Дата": j["issued"], "Контрагент": {"Наименование": j["client"], "ИНН": j["inn"]},
                              "Сумма": j["amount"], "СрокОплаты": j["due"], "Договор": j.get("contract"), "Оплачен": False,
                              "СуммаОплаты": 0.0, "ДатаОплаты": None, "Комментарий": f"Услуги за {j['period']}"})
    if b.cid == "S02":
        for s in sales_inv:
            if s["Контрагент"]["Наименование"] == ANCHOR.name and not s["Оплачен"] and s["СрокОплаты"] < end.isoformat():
                s["Комментарий"] += ". Клиент сообщил о задержке оплаты (письмо от 21.10.2026), новую дату не назвал"
        supp_inv.append({"Номер": "СЛ-2026/1187", "Дата": "2026-10-19", "Контрагент": {"Наименование": "ООО «Софт Лицензии»", "ИНН": fake_inn("ООО «Софт Лицензии»")},
                         "Сумма": 365_000.0, "СрокОплаты": "2026-11-02", "Оплачен": False, "СуммаОплаты": 0.0,
                         "Комментарий": "Годовое продление лицензий средств разработки"})
        b.ops.append(Op(date(2026, 11, 2), "out", 365_000.0, Party("ООО «Софт Лицензии»", fake_inn("ООО «Софт Лицензии»")),
                        "Оплата по счету №СЛ-2026/1187 от 19.10.2026 за продление лицензий. НДС не облагается", "utilities"))
    for o in b.ops:
        if o.direction == "out" and o.kind == "suppliers" and end < o.date <= horizon and o.party.inn and "субподряд" in o.purpose:
            supp_inv.append({"Номер": f"А-{o.date.strftime('%m%d')}", "Дата": (o.date - timedelta(days=10)).isoformat(),
                             "Контрагент": {"Наименование": o.party.name, "ИНН": o.party.inn}, "Сумма": round(o.amount, 2),
                             "СрокОплаты": o.date.isoformat(), "Оплачен": False, "СуммаОплаты": 0.0,
                             "Комментарий": "Акт субподрядчика принят, к оплате"})
    contracts_1c = []
    seen = set()
    for o in b.ops:
        c = o.meta.get("contract")
        if c and c["number"] not in seen and date.fromisoformat(c["signed"]) <= end:
            stages = [x.meta["contract"] for x in b.ops if x.meta.get("contract", {}).get("number") == c["number"]]
            if all(date.fromisoformat(s["planned"]) <= end - timedelta(days=60) for s in stages):
                continue
            seen.add(c["number"])
            contracts_1c.append({"Номер": c["number"], "Дата": c["signed"], "ВидДоговора": "СПокупателем",
                                 "Контрагент": {"Наименование": c["client"], "ИНН": c["inn"]}, "Сумма": round(c["value"], 2),
                                 "ПредоплатаПроцент": int(c["prepay"] * 100), "ОтсрочкаДней": 0,
                                 "ГрафикПлатежей": [{"Дата": s["planned"], "Сумма": round(x.amount, 2), "Этап": s["stage"]}
                                                    for x in b.ops if (s := x.meta.get("contract")) and s["number"] == c["number"]]})
    payroll_docs = []
    for o in b.ops:
        p = o.meta.get("payroll")
        if p and end < o.date <= horizon:
            payroll_docs.append({"Номер": str(p["registry"]), "ДатаВыплаты": o.date.isoformat(), "Вид": p["kind"],
                                 "Сумма": round(o.amount, 2), "Сотрудников": p["employees"]})
    out["1c_export.json"] = {
        "Формат": "Выгрузка из учётной системы (1С:Бухгалтерия), JSON", "ВерсияФормата": "1.2",
        "ДатаВыгрузки": f"{end.isoformat()}T18:00:00", "Организация": org,
        "Документы": {"СчетНаОплатуПокупателю": sales_inv, "СчетОтПоставщика": supp_inv, "Договор": contracts_1c,
                      "ВедомостьНаВыплатуЗарплаты": payroll_docs}}

    loans: dict[str, list[dict[str, Any]]] = {}
    for o in b.ops:
        l = o.meta.get("loan")
        if l and end < o.date <= end + timedelta(days=120):
            loans.setdefault(l["contract"], []).append({"Дата": o.date.isoformat(), "Сумма": round(o.amount, 2)})
    payroll_project = [{"Дата": o.date.isoformat(), "Вид": o.meta["payroll"]["kind"], "Сумма": round(o.amount, 2),
                        "Сотрудников": o.meta["payroll"]["employees"]}
                       for o in b.ops if o.meta.get("payroll") and end < o.date <= horizon]
    orders = []
    for o in b.ops:
        if o.direction == "out" and end < o.date <= end + timedelta(days=14) and o.kind in ("rent", "suppliers", "utilities") \
                and o.party.inn and len(orders) < 6 and o.party.name != "АО «Донэнергосбыт»":
            orders.append({"Номер": str(400 + len(orders)), "Дата": o.date.isoformat(), "Сумма": round(o.amount, 2),
                           "Получатель": {"Наименование": o.party.name, "ИНН": o.party.inn}, "Назначение": o.purpose,
                           "Статус": "Создано, ожидает подписи" if len(orders) % 2 else "Подписано, в очереди на дату"})
    out["bank.json"] = {
        "Банк": BANK.name, "Клиент": org, "ДатаВыгрузки": f"{end.isoformat()}T18:00:00",
        "Кредиты": [{"Договор": k, "Кредитор": BANK.name, "График": v} for k, v in loans.items()],
        "ЗарплатныйПроект": {"Договор": "ЗП-" + b.cid, "Ведомости": payroll_project},
        "ПлатежныеПоручения": orders}

    cps: dict[str, Party] = {}
    for o in b.ops:
        if o.direction == "in" and o.kind == "revenue" and len(o.party.inn) == 10 and o.date > end - timedelta(days=365):
            cps[o.party.inn] = o.party
    checks = []
    for inn, party in sorted(cps.items()):
        risky = party.name == ANCHOR.name and b.cid == "S02"
        checks.append({
            "ИНН": inn, "Наименование": party.name, "Статус": "Действующее",
            "Банкротство": False,
            "ЗадолженностьПоНалогам": 1_840_000.0 if risky else 0.0,
            "АрбитражныеДелаОтветчик12мес": 7 if risky else int(hashlib.md5(inn.encode()).digest()[0] % 2),
            "ИсполнительныеПроизводства": 3 if risky else 0,
            "Источники": ["ЕГРЮЛ", "Федресурс (ЕФРСБ)", "ФНС: сведения о задолженности", "Картотека арбитражных дел", "ФССП"],
        })
    gov = []
    if b.cid == "S03":
        gov.append({"РеестровыйНомер": "3616300112626000047", "Заказчик": {"Наименование": "МКУ «Управление капитального строительства»", "ИНН": fake_inn("МКУ «Управление капитального строительства»")},
                    "Предмет": "Капитальный ремонт кровли МБОУ СОШ №52", "Цена": 3_150_000.0,
                    "Этапы": [{"Дата": (end + timedelta(days=24)).isoformat(), "Сумма": 1_260_000.0, "Описание": "Оплата 1 этапа по акту КС-2"}]})
    if b.cid == "S02":
        gov.append({"РеестровыйНомер": "2616301234526000112", "Заказчик": {"Наименование": "МБУ «Центр цифровизации»", "ИНН": fake_inn("МБУ «Центр цифровизации»")},
                    "Предмет": "Сопровождение информационных систем учреждения", "Цена": 1_260_000.0,
                    "Этапы": [{"Дата": "2026-11-20", "Сумма": 420_000.0, "Описание": "Оплата этапа 2 (октябрь)"}]})
        b.ops.append(Op(date(2026, 11, 23), "in", 420_000.0, Party("МБУ «Центр цифровизации»", fake_inn("МБУ «Центр цифровизации»")),
                        "Оплата по контракту №2616301234526000112, этап 2. НДС не облагается", "revenue"))
    out["registry.json"] = {"ДатаПроверки": f"{end.isoformat()}T18:00:00", "Контрагенты": checks, "Госконтракты": gov}

    contracts = []
    for c in contracts_1c:
        contracts.append({"number": c["Номер"], "counterparty_name": c["Контрагент"]["Наименование"],
                          "counterparty_inn": c["Контрагент"]["ИНН"], "direction": "in", "total_amount": c["Сумма"],
                          "signed_date": c["Дата"], "prepayment_percent": c["ПредоплатаПроцент"], "deferral_days": 0,
                          "schedule": [{"date": s["Дата"], "amount": s["Сумма"], "note": s["Этап"]} for s in c["ГрафикПлатежей"]]})
    if b.cid == "S02":
        contracts.append({"number": "П-2026/33", "counterparty_name": "ООО «Северный ритейл»", "counterparty_inn": fake_inn("ООО «Северный ритейл»"),
                          "direction": "in", "total_amount": 960_000.0, "signed_date": "2026-10-20", "prepayment_percent": 30,
                          "deferral_days": 10, "schedule": [
                              {"date": "2026-10-27", "amount": 288_000.0, "note": "предоплата 30% за внедрение кассовой системы"},
                              {"date": "2026-12-15", "amount": 672_000.0, "note": "окончательный расчёт после акта"}]})
        b.ops.append(Op(date(2026, 10, 29), "in", 288_000.0, Party("ООО «Северный ритейл»", fake_inn("ООО «Северный ритейл»")),
                        "Предоплата 30% по договору №П-2026/33 от 20.10.2026. в т.ч. НДС (22%) 51 934,43", "revenue"))
    out["contracts.json"] = contracts
    inv_rows = [["number", "direction", "counterparty_name", "counterparty_inn", "amount", "issue_date", "due_date", "paid_amount", "note"]]
    for s in sales_inv:
        inv_rows.append([s["Номер"], "in", s["Контрагент"]["Наименование"], s["Контрагент"]["ИНН"], f"{s['Сумма']:.2f}", s["Дата"],
                         s["СрокОплаты"], f"{s['СуммаОплаты']:.2f}", s["Комментарий"]])
    for s in supp_inv:
        inv_rows.append([s["Номер"], "out", s["Контрагент"]["Наименование"], s["Контрагент"]["ИНН"], f"{s['Сумма']:.2f}", s["Дата"],
                         s["СрокОплаты"], f"{s['СуммаОплаты']:.2f}", s["Комментарий"]])
    out["invoices.csv"] = inv_rows
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Генератор синтетических банковских выписок малого бизнеса (демо и тесты)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent))
    ap.add_argument("--end", default="2026-10-23", help="последний день выписки (рабочий)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--format", choices=["raw", "internal"], default="raw")
    ap.add_argument("--only", nargs="*", help="id компаний, напр. S02")
    args = ap.parse_args()
    out = Path(args.out)
    end = prev_bd(date.fromisoformat(args.end))
    companies = []
    for spec in COMPANIES:
        if args.only and spec[0] not in args.only:
            continue
        b, hist, fut = build_company(spec, end, args.seed)
        integ = integrations_for(b, end)
        _, _, fut = _refresh_future(b, end)
        write_statement(out / "statements" / f"{b.cid}.csv", b.cid, hist, args.format)
        write_statement(out / "future" / f"{b.cid}.csv", b.cid, fut, args.format)
        d = out / "integrations" / b.cid
        d.mkdir(parents=True, exist_ok=True)
        for name, payload in integ.items():
            if name.endswith(".csv"):
                with (d / name).open("w", encoding="utf-8-sig", newline="") as f:
                    csv.writer(f, delimiter=";").writerows(payload)
            else:
                (d / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        bal = [r["balance_eod"] for r in hist]
        neg = [r["date"] for r in hist if r["balance_eod"] < 0]
        companies.append({"company_id": b.cid, "company_name": b.name, "company_inn": b.inn, "legal_form": b.legal_form,
                          "industry": b.industry, "first_operation_date": hist[0]["date"].isoformat(),
                          "last_operation_date": hist[-1]["date"].isoformat(), "operations_count": len(hist)})
        fut_min = min((r["balance_eod"], r["date"]) for r in fut) if fut else (None, None)
        print(f"{b.cid}: {len(hist):5d} операций {hist[0]['date']}…{hist[-1]['date']}, остаток {bal[-1]:>13,.0f}, "
              f"мин {min(bal):>13,.0f}, дней < 0: {len(set(neg))}"
              + (f" ({min(neg)}…{max(neg)})" if neg else "")
              + (f"; будущее: мин {fut_min[0]:,.0f} на {fut_min[1]}" if fut else ""))
    with (out / "companies.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(companies[0]), delimiter=";")
        w.writeheader()
        w.writerows(companies)


def _refresh_future(b: Book, end: date) -> tuple[Book, list, list[dict[str, Any]]]:
    ops = sorted(b.ops, key=lambda o: (o.date, 0 if o.direction == "in" else 1))
    bal = b.start_balance
    fut = []
    by_day: dict[date, list[Op]] = {}
    for o in ops:
        by_day.setdefault(o.date, []).append(o)
    for d in sorted(by_day):
        bal += sum(o.amount if o.direction == "in" else -o.amount for o in by_day[d])
        if d > end:
            for o in by_day[d]:
                fut.append({"date": d, "amount": o.amount, "direction": o.direction, "counterparty_inn": o.party.inn,
                            "counterparty_name": o.party.name, "purpose": o.purpose, "balance_eod": round(bal, 2)})
    return b, [], fut


if __name__ == "__main__":
    main()
