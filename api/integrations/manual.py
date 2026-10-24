from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from ..schemas import EventCreate
from ..textfmt import MONTHS_GEN, day_month, rub
from .base import CompanyContext, Integration, SourceEvent

_MONTH_STEMS = ["январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр"]
_AMOUNT_RX = re.compile(r"(\d[\d\s ]*(?:[.,]\d+)?)\s*(млн|миллион\w*|тыс\w*|т\.?р\.?|к(?![а-я]))?\s*(?:₽|руб\w*|р\.(?!\w))?", re.I)
_IN_WORDS = ("клиент", "покупател", "заказчик", "обещал", "поступ", "получ", "придет", "придёт", "вернут", "вернёт",
             "вернет", "оплатит нам", "переведут", "заплатят", "аванс от", "предоплат от")
_OUT_WORDS = ("куплю", "купим", "купить", "покупк", "закуп", "оплатить", "заплатить поставщ", "штраф", "ремонт",
              "налог", "аренд", "зарплат", "расход", "кредит", "лизинг", "доначисл", "оборудован", "отдать", "вернуть долг")


def _amount(text: str) -> float | None:
    best = None
    for m in _AMOUNT_RX.finditer(text):
        num, mult = m.group(1), (m.group(2) or "").lower()
        digits = num.replace(" ", "").replace(" ", "").replace(",", ".")
        try:
            v = float(digits)
        except ValueError:
            continue
        tail = text[m.end(1):m.end(1) + 3]
        if not mult and re.match(r"\s*-?\s*(го|е|ого|числ)", text[m.end(1):m.end(1) + 6]):
            continue
        if re.match(r"\.\d", tail) or re.match(r"\s*(январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)", text[m.end(1):m.end(1) + 10], re.I):
            continue
        if mult.startswith("млн") or mult.startswith("миллион"):
            v *= 1_000_000
        elif mult.startswith(("тыс", "т")) or mult == "к":
            v *= 1_000
        if v >= 100 and (best is None or v > best):
            best = v
    return best


def _next_day_of_month(today: date, day: int) -> date:
    y, m = today.year, today.month
    for _ in range(13):
        last = calendar.monthrange(y, m)[1]
        cand = date(y, m, min(day, last))
        if cand > today:
            return cand
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return today + timedelta(days=30)


def _date(text: str, today: date, direction: str) -> tuple[date, str]:
    t = text.lower()
    if "послезавтра" in t:
        return today + timedelta(days=2), "послезавтра"
    if "завтра" in t:
        return today + timedelta(days=1), "завтра"
    m = re.search(r"через\s+(\d+)?\s*(дн|день|недел|месяц)[а-яё]*", t)
    if m:
        n = int(m.group(1) or 1)
        k = {"дн": 1, "ден": 1, "нед": 7, "мес": 30}[m.group(2)[:3] if m.group(2)[:3] in ("нед", "мес") else "дн"]
        return today + timedelta(days=n * k), m.group(0)
    if "следующей неделе" in t:
        return today + timedelta(days=7 - today.weekday()), "в начале следующей недели"
    m = re.search(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?", t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else today.year
        y = y + 2000 if y < 100 else y
        try:
            res = date(y, mo, d)
            if not m.group(3) and res <= today:
                res = date(y + 1, mo, d)
            return res, m.group(0)
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})\s*(январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*", t)
    if m:
        mo = next(i + 1 for i, s in enumerate(_MONTH_STEMS) if m.group(2).startswith(s))
        y = today.year
        res = date(y, mo, min(int(m.group(1)), calendar.monthrange(y, mo)[1]))
        if res <= today:
            res = date(y + 1, mo, min(int(m.group(1)), calendar.monthrange(y + 1, mo)[1]))
        return res, m.group(0)
    m = re.search(r"(\d{1,2})\s*(?:-?\s*(?:го|е|ого)\b|числа)", t)
    if m:
        return _next_day_of_month(today, int(m.group(1))), m.group(0)
    m = re.search(r"в\s+(январ|феврал|март|апрел|ма[ея]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*", t)
    if m:
        mo = next(i + 1 for i, s in enumerate(_MONTH_STEMS) if m.group(1).startswith(s))
        y = today.year if mo > today.month else today.year + 1
        d = date(y, mo, 1) if direction == "out" else date(y, mo, calendar.monthrange(y, mo)[1])
        return d, m.group(0) + (" (берём начало месяца)" if direction == "out" else " (берём конец месяца)")
    return today + timedelta(days=7), "дата не указана — через неделю"


def _counterparty(text: str) -> str | None:
    m = re.search(r"((?:ООО|АО|ПАО|ЗАО|ИП|МУП|ГУП|МКУ|МБУ)\s*«[^»]+»)", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"«([^»]+)»", text)
    if m:
        return f"«{m.group(1)}»"
    m = re.search(r"\b(ИП\s+[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ]\.\s*[А-ЯЁ]\.)?)", text)
    return m.group(1) if m else None


def parse_text(text: str, today: date) -> tuple[EventCreate, str]:
    low = text.lower()
    in_score = sum(w in low for w in _IN_WORDS)
    out_score = sum(w in low for w in _OUT_WORDS)
    direction = "in" if in_score > out_score else "out"
    amount = _amount(text)
    if amount is None:
        raise ValueError("Не нашли сумму. Напишите, например: «клиент обещал заплатить 300 000 ₽ 20-го».")
    when, how = _date(text, today, direction)
    etype = "manual"
    if "налог" in low or "енп" in low:
        etype = "tax"
    elif "зарплат" in low:
        etype = "payroll"
    elif "кредит" in low:
        etype = "loan"
    elif "счет" in low or "счёт" in low:
        etype = "invoice"
    elif "договор" in low:
        etype = "contract"
    cp = _counterparty(text)
    ev = EventCreate(type=etype, direction=direction, amount=round(amount, 2), date=when, source="manual",
                     status="expected", counterparty=cp, note=text.strip()[:300])
    understood = (f"{'Поступление' if direction == 'in' else 'Списание'} {rub(amount)} {day_month(when)} {when.year}"
                  + (f", {cp}" if cp else "") + f" (дата: {how})")
    return ev, understood


class Manual(Integration):
    name = "manual"
    title = "Ручной ввод"
    source = "manual"
    description = "«Клиент обещал заплатить 300 000 ₽ 20-го», «в декабре куплю оборудование за 1 млн»"

    def fetch(self, company: CompanyContext) -> list[SourceEvent]:
        return []


__all__ = ["parse_text", "Manual", "MONTHS_GEN"]
