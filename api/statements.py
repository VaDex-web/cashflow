"""Приём выписки: проверка файла, терпимый разбор, понятные ошибки на русском.

Сначала быстрая проверка (кодировка, разделитель, колонки), чтобы сразу сказать человеку, что не так.
Затем чистка: настоящим ядром (``cashflow_core.load_statement``) или собственным разбором (заглушка).
Понимает формат датасета организаторов (п. 1.1 контракта) и внутренний (п. 1.2), русские заголовки,
``;``/``,``/табуляцию, BOM, cp1251, знаковую сумму, «Дебет/Кредит», даты ДД.ММ.ГГГГ, суммы «1 234,56».
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Any

import pandas as pd


class StatementError(ValueError):
    """Ошибка разбора выписки — текст показывается пользователю."""


ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "operation_date", "дата", "дата операции", "дата проводки", "дата платежа", "operation date",
             "transaction date", "дата документа"),
    "amount": ("amount", "сумма", "сумма операции", "сумма платежа", "sum", "сумма, руб", "сумма руб", "сумма (руб)"),
    "direction": ("direction", "направление", "тип операции", "вид операции", "тип", "приход/расход", "дебет/кредит"),
    "debit": ("debit", "дебет", "списание", "расход", "сумма по дебету", "сумма списания"),
    "credit": ("credit", "кредит", "поступление", "приход", "сумма по кредиту", "сумма поступления"),
    "counterparty_name": ("counterparty_name", "counterparty", "контрагент", "наименование контрагента",
                          "получатель/плательщик", "плательщик/получатель", "корреспондент"),
    "counterparty_inn": ("counterparty_inn", "inn", "инн", "инн контрагента", "инн корреспондента"),
    "purpose": ("purpose", "payment_purpose", "назначение", "назначение платежа", "description", "комментарий"),
    "balance_eod": ("balance_eod", "balance", "остаток", "остаток на конец дня", "исходящий остаток", "closing balance"),
    "company_id": ("company_id", "компания", "id компании"),
    "operation_id": ("operation_id", "id", "номер операции"),
}
REQUIRED_HINT = "дата, сумма, направление (поступление/списание), контрагент, ИНН, назначение платежа, остаток на конец дня"


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", str(h).replace("﻿", "").strip().strip('"').lower().replace("_", " ")).strip()


def decode(raw: bytes) -> str:
    if not raw or not raw.strip():
        raise StatementError("Файл пустой.")
    if raw[:2] == b"PK":
        raise StatementError("Это файл Excel (XLSX). Сохраните выписку в формате CSV: «Файл → Сохранить как → CSV UTF-8».")
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise StatementError("Не удалось прочитать кодировку файла. Сохраните выписку в UTF-8 (в Excel: «CSV UTF-8»).")


def _sniff(text: str) -> tuple[str, int]:
    """Разделитель и номер строки заголовка (над таблицей бывает «шапка» выписки)."""
    lines = text.splitlines()[:30]
    for i, line in enumerate(lines):
        low = line.lower()
        if re.search(r"(date|дата)", low) and re.search(r"(amount|сумм|дебет|кредит|приход|расход)", low):
            counts = {d: line.count(d) for d in (";", ",", "\t")}
            delim = max(counts, key=lambda k: counts[k])
            if counts[delim] == 0:
                break
            return delim, i
    raise StatementError(f"Не нашли строку с названиями колонок. В первой строке таблицы должны быть колонки: {REQUIRED_HINT}.")


def map_columns(headers: list[str]) -> dict[str, str]:
    norm = {_norm(h): h for h in headers}
    out: dict[str, str] = {}
    for key, names in ALIASES.items():
        for n in names:
            if _norm(n) in norm and norm[_norm(n)] not in out.values():
                out[key] = norm[_norm(n)]
                break
    return out


def check_header(raw: bytes) -> tuple[str, list[str], dict[str, str], int]:
    """Проверить файл до разбора. Возвращает (текст, заголовки, сопоставление колонок, строка заголовка)."""
    text = decode(raw)
    delim, hdr = _sniff(text)
    reader = csv.reader(io.StringIO("\n".join(text.splitlines()[hdr:hdr + 1])), delimiter=delim)
    headers = next(reader, [])
    cols = map_columns(headers)
    missing = []
    if "date" not in cols:
        missing.append("дата операции")
    if "amount" not in cols and not ("debit" in cols or "credit" in cols):
        missing.append("сумма")
    if "amount" in cols and "direction" not in cols and not ("debit" in cols or "credit" in cols):
        # допустима знаковая сумма — проверим при разборе
        pass
    if missing:
        raise StatementError(f"Не нашли колонки: {', '.join(missing)}. Есть: {', '.join(h.strip() for h in headers[:12])}. "
                             f"Нужны колонки: {REQUIRED_HINT}.")
    return text, headers, cols, hdr


_NUM_RX = re.compile(r"[^\d,.\-−()]")


def parse_amount(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "").replace(" ", "")
    if not s:
        return None
    neg = s.startswith(("-", "−")) or (s.startswith("(") and s.endswith(")"))
    s = _NUM_RX.sub("", s).replace("−", "-").strip("()-")
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def parse_date(v: Any) -> date | None:
    if isinstance(v, date):
        return v
    s = str(v or "").strip()[:19]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d.%m.%y"):
        try:
            return datetime.strptime(s if "%H" in fmt else s[:10], fmt).date()
        except ValueError:
            continue
    return None


def parse_direction(v: Any) -> str | None:
    s = str(v or "").strip().lower()
    if not s:
        return None
    if s in ("in", "+", "c", "cr", "к", "кт", "credit", "income") or s.startswith(("пост", "зачисл", "прих", "кред", "вход")):
        return "in"
    if s in ("out", "-", "d", "dr", "д", "дт", "debit") or s.startswith(("спис", "расх", "деб", "плат", "исход", "выпл")):
        return "out"
    return None


def normalize_row(r: dict[str, Any], cols: dict[str, str] | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """Одна строка → внутренний формат (п. 1.2) или (None, причина пропуска)."""
    g = (lambda k: r.get(cols[k]) if cols and k in cols else r.get(k))
    d = parse_date(g("date") if g("date") is not None else r.get("operation_date"))
    if d is None:
        return None, "дата"
    amount = parse_amount(g("amount"))
    direction = parse_direction(g("direction"))
    if amount is None and cols and ("debit" in cols or "credit" in cols):
        deb, cred = parse_amount(g("debit")) or 0.0, parse_amount(g("credit")) or 0.0
        amount, direction = (cred, "in") if cred else (deb, "out")
    if amount is None:
        return None, "сумма"
    if direction is None:
        direction = "out" if amount < 0 else "in"
    amount = abs(amount)
    if amount == 0:
        return None, "нулевая сумма"
    inn = str(g("counterparty_inn") or "").strip()
    if inn.endswith(".0"):
        inn = inn[:-2]
    bal = parse_amount(g("balance_eod"))
    purpose = g("purpose")
    if purpose is None:
        purpose = r.get("payment_purpose")
    return {"date": d, "amount": round(amount, 2), "direction": direction,
            "counterparty_name": str(g("counterparty_name") or "").strip(), "counterparty_inn": inn,
            "purpose": str(purpose or "").strip(), "balance_eod": bal}, None


def parse_statement_bytes(raw: bytes, company: str | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Собственный терпимый разбор (используется заглушкой ядра и для проверки)."""
    text, headers, cols, hdr = check_header(raw)
    delim = _sniff(text)[0]
    reader = csv.DictReader(io.StringIO("\n".join(text.splitlines()[hdr:])), delimiter=delim)
    rows, skipped, seen, dups = [], {}, set(), 0
    for r in reader:
        if company and cols.get("company_id") and str(r.get(cols["company_id"], "")).strip() != company:
            continue
        row, why = normalize_row(r, cols)
        if row is None:
            if any(str(v or "").strip() for v in r.values()):
                skipped[why] = skipped.get(why, 0) + 1
            continue
        key = tuple(row.values())
        if key in seen:
            dups += 1
        seen.add(key)
        rows.append(row)
    warnings = []
    if skipped:
        warnings.append("Пропущены строки с ошибками: " + ", ".join(f"{k} — {v}" for k, v in skipped.items()) + ".")
    if dups:
        warnings.append(f"В файле есть одинаковые строки ({dups}) — возможно, дубли выгрузки.")
    if "balance_eod" not in cols:
        warnings.append("Нет колонки с остатком на конец дня — остаток посчитан по операциям.")
    if not rows:
        raise StatementError("Не удалось прочитать ни одной операции. Проверьте формат дат (ГГГГ-ММ-ДД или ДД.ММ.ГГГГ) и сумм.")
    return rows, warnings


def companies_in_file(raw: bytes) -> list[str]:
    text, headers, cols, hdr = check_header(raw)
    if "company_id" not in cols:
        return []
    delim = _sniff(text)[0]
    reader = csv.DictReader(io.StringIO("\n".join(text.splitlines()[hdr:])), delimiter=delim)
    seen: dict[str, None] = {}
    for r in reader:
        v = str(r.get(cols["company_id"], "")).strip()
        if v:
            seen[v] = None
    return list(seen)


def frame_from_core(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Результат ``load_statement`` ядра → строки для хранения."""
    out = []
    for r in df.itertuples(index=False):
        d = r.date.date() if hasattr(r.date, "date") else parse_date(r.date)
        bal = getattr(r, "balance_eod", None)
        out.append({"date": d, "amount": float(r.amount), "direction": str(r.direction),
                    "counterparty_name": str(getattr(r, "counterparty_name", "") or ""),
                    "counterparty_inn": str(getattr(r, "counterparty_inn", "") or ""),
                    "purpose": str(getattr(r, "purpose", "") or ""),
                    "balance_eod": None if bal is None or pd.isna(bal) else float(bal)})
    return out


def select_company(raw: bytes, company: str | None) -> bytes:
    """Из файла с несколькими компаниями (all_operations.csv) оставить одну."""
    text, headers, cols, hdr = check_header(raw)
    delim = _sniff(text)[0]
    lines = text.splitlines()
    out = [lines[hdr]]
    rdr = csv.reader(io.StringIO("\n".join(lines[hdr + 1:])), delimiter=delim)
    idx = headers.index(cols["company_id"])
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delim)
    for row in rdr:
        if len(row) > idx and row[idx].strip() == company:
            w.writerow(row)
    body = buf.getvalue()
    if not body.strip():
        raise StatementError(f"В файле нет операций компании {company}.")
    return ("\n".join(out) + "\n" + body).encode("utf-8")
