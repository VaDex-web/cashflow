"""Мини-генератор синтетических выписок для тестов ядра.

Не путать с генератором демо-данных в ``data/synthetic`` (его ведёт api/) — этот нужен только
тестам: маленький, детерминированный (seed), с известной «правдой»
(колонка ``true_category``) и управляемыми граничными случаями.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cashflow_core.calendar_ru import is_business_day, shift_to_business_day  # noqa: E402

BANK = ("ПАО «Банк»", "0068275202")
FNS = ("Казначейство России (ФНС России)", "7727406020")


def _month_day(y: int, m: int, d: int) -> date:
    import calendar

    return date(y, m, min(d, calendar.monthrange(y, m)[1]))


def generate_statement(
    days: int = 400,
    start: str = "2025-01-09",
    seed: int = 42,
    start_balance: float = 800_000.0,
    revenue_level: float = 60_000.0,
    payroll: float = 300_000.0,
    expense_ratio: float = 1.0,
    giant_client: bool = False,
    empty_purpose_share: float = 0.02,
    fmt: str = "contract",
) -> pd.DataFrame:
    """Сгенерировать выписку.

    Args:
        days: длина истории в календарных днях.
        revenue_level: средняя дневная выручка эквайринга.
        expense_ratio: множитель расходов (> 1 — компания «проедает» деньги → будет разрыв).
        giant_client: добавить клиента, дающего > 50% выручки.
        fmt: "contract" (стандартные колонки) | "dataset" (формат организаторов) | "messy" (русские
            заголовки, знаковая сумма с запятой, даты ДД.ММ.ГГГГ, дубли, пропуск недели).
    """
    rng = np.random.default_rng(seed)
    d0 = date.fromisoformat(start)
    end = d0 + timedelta(days=days - 1)
    rows: list[dict] = []

    def add(d: date, amount: float, direction: str, cp: tuple[str, str], purpose: str, cat: str) -> None:
        if d < d0 or d > end or amount <= 0:
            return
        if rng.random() < empty_purpose_share and cat not in ("taxes",):
            purpose = ""
        rows.append({"date": d, "amount": round(float(amount), 2), "direction": direction,
                     "counterparty_name": cp[0], "counterparty_inn": cp[1], "purpose": purpose, "true_category": cat})

    clients = [(f"ООО «Клиент-{i:02d}»", f"00{rng.integers(10**7, 10**8)}") for i in range(4)]
    suppliers = [(f"ООО «Поставщик-{i:02d}»", f"00{rng.integers(10**7, 10**8)}") for i in range(5)]
    landlord = ("ООО «Арендодатель-01»", "0011223344")
    telecom = ("ПАО «Телеком-01»", "0055667788")
    giant = ("АО «Крупный заказчик»", "0099887766")

    d = d0
    q_rev = 0.0
    while d <= end:
        bd = is_business_day(d)
        if bd:
            # эквайринг за предыдущие дни — на следующий рабочий день
            mult = 1.4 if d.weekday() == 0 else 1.0
            add(d, revenue_level * mult * rng.lognormal(0, 0.25), "in", BANK,
                f"Зачисление средств по операциям эквайринга. Мерчант №4010196. Дата реестра {d - timedelta(days=1):%d.%m.%Y}",
                "revenue")
            q_rev += revenue_level * mult
            if rng.random() < 0.35:
                s = suppliers[rng.integers(0, len(suppliers))]
                add(d, revenue_level * 0.9 * expense_ratio * rng.lognormal(0, 0.5), "out", s,
                    f"Оплата по счету № {rng.integers(100, 999)} от {d:%d.%m.%Y} за товар. В т.ч. НДС 20% - 1 000.00",
                    "suppliers")
        if d.day == 1 or (d == d0):
            y, m = d.year, d.month
            for i, c in enumerate(clients[:3]):
                pd_ = shift_to_business_day(_month_day(y, m, 12 + 3 * i), "forward") + timedelta(days=int(rng.integers(0, 3)))
                add(pd_, 150_000 * (1 + 0.3 * i) * rng.lognormal(0, 0.08), "in", c,
                    f"Оплата по УПД № {rng.integers(100, 999)} от {pd_:%d.%m.%Y}. НДС не облагается", "revenue")
            if giant_client:
                gd = shift_to_business_day(_month_day(y, m, 20), "forward")
                add(gd, revenue_level * 40 * rng.lognormal(0, 0.05), "in", giant, "Оплата по договору № 1/25 за услуги", "revenue")
            add(shift_to_business_day(_month_day(y, m, 10), "backward"), payroll * expense_ratio, "out", BANK,
                f"Перечисление заработной платы (окончательный расчет) за {m:02d}.{y} по реестру № {m}. НДС не облагается", "payroll")
            add(shift_to_business_day(_month_day(y, m, 25), "backward"), payroll * 0.6 * expense_ratio, "out", BANK,
                f"Перечисление заработной платы (аванс) за {m:02d}.{y} по реестру № {m + 20}. НДС не облагается", "payroll")
            tax = payroll * 0.43
            if m in (4, 7, 10):
                tax += 0.06 * q_rev * 0.5
            add(shift_to_business_day(_month_day(y, m, 28), "forward"), tax, "out", FNS,
                ["Единый налоговый платеж", "ЕНП", "Единый налоговый платёж"][m % 3], "taxes")
            if m in (3, 6, 9, 12):
                q_rev = 0.0
            add(shift_to_business_day(_month_day(y, m, 5), "forward"), 120_000 * expense_ratio, "out", landlord,
                f"Оплата аренды нежилого помещения по договору № 12 за {m:02d}.{y}. В т.ч. НДС 20%", "rent")
            add(shift_to_business_day(_month_day(y, m, 8), "forward"), 6000 * rng.lognormal(0, 0.05), "out", telecom,
                "Оплата услуг связи и доступа в Интернет по лицевому счету 1006059", "utilities")
            add(shift_to_business_day(_month_day(y, m, 1), "forward"), 990, "out", BANK,
                "Комиссия за ведение счета. Без НДС", "bank_fees")
        d += timedelta(days=1)

    df = pd.DataFrame(rows).sort_values("date", kind="stable").reset_index(drop=True)
    df["signed"] = np.where(df["direction"] == "in", df["amount"], -df["amount"])
    bal = start_balance + df.groupby("date")["signed"].sum().cumsum()
    df["balance_eod"] = df["date"].map(bal).round(2)
    df = df.drop(columns="signed")
    df["date"] = pd.to_datetime(df["date"])

    if fmt == "dataset":
        out = pd.DataFrame({
            "company_id": "T001", "operation_id": [f"T001-{i:06d}" for i in range(len(df))],
            "operation_date": df["date"].dt.strftime("%Y-%m-%d"), "amount": df["amount"].map(lambda v: f"{v:.2f}"),
            "direction": np.where(df["direction"] == "in", "Поступление", "Списание"),
            "counterparty_inn": df["counterparty_inn"], "counterparty_name": df["counterparty_name"],
            "payment_purpose": df["purpose"], "balance_eod": df["balance_eod"].map(lambda v: f"{v:.2f}"),
            "true_category": df["true_category"]})
        return out
    if fmt == "messy":
        m = df.copy()
        # пропуск недели данных и дубль строки
        gap_start = m["date"].min() + pd.Timedelta(days=days // 2)
        m = m[~m["date"].between(gap_start, gap_start + pd.Timedelta(days=6))]
        m = pd.concat([m, m.iloc[[5]]]).sort_values("date", kind="stable")
        signed = np.where(m["direction"] == "in", m["amount"], -m["amount"])
        return pd.DataFrame({
            "Дата операции": m["date"].dt.strftime("%d.%m.%Y"),
            "Сумма, руб": [f"{v:,.2f}".replace(",", " ").replace(".", ",") for v in signed],
            "Контрагент": m["counterparty_name"].values, "ИНН контрагента": m["counterparty_inn"].values,
            "Назначение платежа": m["purpose"].values,
            "Остаток на конец дня": [f"{v:.2f}".replace(".", ",") for v in m["balance_eod"]],
            "true_category": m["true_category"].values})
    return df


def to_csv_bytes(df: pd.DataFrame, sep: str = ";", encoding: str = "utf-8-sig") -> bytes:
    """CSV в байтах (для проверки кодировок и разделителей)."""
    return df.to_csv(sep=sep, index=False).encode(encoding)
