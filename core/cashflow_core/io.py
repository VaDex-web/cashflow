from __future__ import annotations

import csv
import hashlib
import io
import re
from pathlib import Path
from typing import Any, BinaryIO, Iterable

import numpy as np
import pandas as pd

from .log import get_logger

log = get_logger(__name__)

STANDARD_COLUMNS = [
    "tx_id", "date", "amount", "direction", "signed_amount",
    "counterparty_name", "counterparty_inn", "purpose", "balance_eod",
]

COLUMN_ALIASES: dict[str, list[str]] = {
    "date": ["date", "дата", "дата операции", "дата проводки", "дата платежа", "operation date",
             "posting date", "value date", "transaction date", "dt", "day", "дата документа"],
    "amount": ["amount", "сумма", "сумма операции", "сумма платежа", "sum", "value", "amt",
               "amount rub", "сумма руб", "сумма, руб", "сумма (руб)", "signed amount"],
    "direction": ["direction", "направление", "тип", "тип операции", "вид операции", "type", "dir",
                  "дебет/кредит", "debit/credit", "debit credit", "dc", "operation type", "приход/расход"],
    "debit": ["debit", "дебет", "списание", "списано", "расход", "outflow", "withdrawal",
              "сумма по дебету", "сумма списания", "out"],
    "credit": ["credit", "кредит", "поступление", "зачислено", "приход", "inflow", "deposit",
               "сумма по кредиту", "сумма поступления", "in"],
    "counterparty_name": ["counterparty name", "counterparty", "контрагент", "наименование контрагента",
                          "получатель/плательщик", "плательщик/получатель", "корреспондент", "payee",
                          "payer", "partner", "name", "наименование"],
    "counterparty_inn": ["counterparty inn", "inn", "инн", "инн контрагента", "инн корреспондента",
                         "partner inn", "tax id"],
    "purpose": ["purpose", "назначение", "назначение платежа", "description", "comment", "details",
                "memo", "основание", "комментарий", "описание"],
    "balance_eod": ["balance eod", "balance", "остаток", "остаток на конец дня", "исходящий остаток",
                    "closing balance", "balance end", "eod balance", "остаток на конец"],
    "source_id": ["id", "tx id", "transaction id", "operation id", "uid", "идентификатор операции"],
    "company_id": ["company id", "company", "client id", "компания", "id компании"],
}
COLUMN_ALIASES["purpose"] += ["payment purpose", "payment_purpose"]
COLUMN_ALIASES["date"] += ["operation date", "operation_date"]

_FUZZY: list[tuple[str, tuple[str, ...]]] = [
    ("counterparty_inn", ("инн", "inn")),
    ("balance_eod", ("остат", "balance")),
    ("purpose", ("назначен", "purpose", "descr")),
    ("date", ("дата", "date")),
    ("debit", ("дебет", "списан", "debit")),
    ("credit", ("кредит", "поступл", "зачисл", "credit")),
    ("amount", ("сумм", "amount")),
    ("counterparty_name", ("контрагент", "получател", "плательщ", "counterparty", "корреспондент")),
]

_IN_WORDS = ("in", "inflow", "credit", "cr", "c", "к", "кт", "+", "income", "incoming", "приход")
_OUT_WORDS = ("out", "outflow", "debit", "dr", "d", "д", "дт", "-", "expense", "outgoing", "расход")
_IN_PREFIX = ("пост", "зачисл", "прих", "кред", "вход", "incom", "receiv")
_OUT_PREFIX = ("спис", "расх", "деб", "выпл", "плат", "исход", "outg", "paym", "withdr")

_DATE_FORMATS = [
    "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%d.%m.%y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
    "%m/%d/%Y", "%Y%m%d",
]


def _norm_header(h: Any) -> str:
    s = str(h).replace("﻿", "").strip().lower().replace("ё", "е")
    s = re.sub(r"[\"'«»]", "", s)
    s = re.sub(r"[_\.]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _match_columns(headers: Iterable[Any]) -> dict[str, str]:
    headers = list(headers)
    normed = {h: _norm_header(h) for h in headers}
    mapping: dict[str, str] = {}
    used: set[Any] = set()
    for std, aliases in COLUMN_ALIASES.items():
        al = {_norm_header(a) for a in aliases}
        for h in headers:
            if h not in used and normed[h] in al:
                mapping[std] = h
                used.add(h)
                break
    for std, subs in _FUZZY:
        if std in mapping:
            continue
        for h in headers:
            if h in used:
                continue
            n = normed[h]
            if any(s in n for s in subs):
                if std in ("debit", "credit") and "/" in n:
                    continue
                mapping[std] = h
                used.add(h)
                break
    return mapping


def parse_number(x: Any) -> float:
    if x is None:
        return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)) and not isinstance(x, bool):
        return float(x)
    s = str(x).strip()
    if not s or s.lower() in ("nan", "none", "null", "-", "—"):
        return np.nan
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    s = s.replace("−", "-").replace("–", "-")
    s = re.sub(r"(?i)(₽|руб\.?|rub|р\.|rur)", "", s)
    s = re.sub(r"[\s  ']", "", s)
    if s.endswith("-"):
        neg, s = True, s[:-1]
    if s.startswith("+"):
        s = s[1:]
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        if re.fullmatch(r"-?\d{1,3}(,\d{3})+", s):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return np.nan
    return -v if neg else v


def parse_dates(values: pd.Series) -> tuple[pd.Series, list[str]]:
    s = values.astype(str).str.strip()
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    used: list[str] = []
    num = pd.to_numeric(s, errors="coerce")
    excel_mask = num.between(20000, 80000) & s.str.fullmatch(r"\d+(\.\d+)?")
    if excel_mask.any():
        out[excel_mask] = pd.to_datetime(num[excel_mask], unit="D", origin="1899-12-30")
        used.append("excel_serial")
    remaining = out.isna() & s.ne("") & ~s.str.lower().isin(["nan", "none", "nat"])
    while remaining.any():
        best_fmt, best_parsed, best_n = None, None, 0
        for fmt in _DATE_FORMATS:
            parsed = pd.to_datetime(s[remaining], format=fmt, errors="coerce")
            n = int(parsed.notna().sum())
            if n > best_n:
                best_fmt, best_parsed, best_n = fmt, parsed, n
        if best_n == 0:
            break
        out[best_parsed.dropna().index] = best_parsed.dropna()
        used.append(str(best_fmt))
        remaining = out.isna() & remaining
    if remaining.any():
        parsed = pd.to_datetime(s[remaining], format="mixed", dayfirst=True, errors="coerce")
        if parsed.notna().any():
            out[parsed.dropna().index] = parsed.dropna()
            used.append("mixed")
    return out.dt.normalize(), used


def _parse_direction(v: Any) -> str | None:
    s = str(v).strip().lower().replace("ё", "е")
    if not s or s in ("nan", "none"):
        return None
    if s in _IN_WORDS:
        return "in"
    if s in _OUT_WORDS:
        return "out"
    if s.startswith(_IN_PREFIX):
        return "in"
    if s.startswith(_OUT_PREFIX):
        return "out"
    return None


def _read_any(src: str | Path | BinaryIO | bytes) -> pd.DataFrame:
    if isinstance(src, (str, Path)):
        p = Path(src)
        if p.suffix.lower() in (".xlsx", ".xls"):
            return pd.read_excel(p, dtype=str, header=None)
        raw = p.read_bytes()
    elif isinstance(src, bytes):
        raw = src
    else:
        raw = src.read()
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
    text = None
    for enc in ("utf-8-sig", "cp1251", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    assert text is not None
    sep, start = _detect_layout(text)
    text = "\n".join(text.splitlines()[start:])
    return pd.read_csv(io.StringIO(text), sep=sep, dtype=str, header=None, keep_default_na=False,
                       skip_blank_lines=True, engine="python", on_bad_lines="skip")


def _detect_layout(text: str) -> tuple[str, int]:
    lines = text.splitlines()[:300]
    best = (",", 0, -1)
    for sep in (";", ",", "\t", "|"):
        widths = [len(r) for r in csv.reader(lines, delimiter=sep)] if lines else []
        if not widths:
            continue
        vals, cnts = np.unique([w for w in widths if w > 1] or [1], return_counts=True)
        mode, freq = int(vals[cnts.argmax()]), int(cnts.max())
        if mode > 1 and freq > best[2]:
            start = next((i for i, w in enumerate(widths) if w == mode), 0)
            best = (sep, start, freq)
    return best[0], best[1]


def _find_header(raw: pd.DataFrame) -> pd.DataFrame:
    best_row, best_score = 0, -1
    for i in range(min(25, len(raw))):
        m = _match_columns([c for c in raw.iloc[i].tolist() if str(c).strip()])
        score = len(m) + (3 if "date" in m else 0)
        if score > best_score:
            best_row, best_score = i, score
    header = [str(c) if str(c).strip() else f"col{j}" for j, c in enumerate(raw.iloc[best_row].tolist())]
    seen: dict[str, int] = {}
    for j, h in enumerate(header):
        if h in seen:
            seen[h] += 1
            header[j] = f"{h}.{seen[h]}"
        else:
            seen[h] = 0
    df = raw.iloc[best_row + 1:].copy()
    df.columns = header
    return df.reset_index(drop=True)


def _tx_ids(df: pd.DataFrame) -> pd.Series:
    key = (
        df["date"].dt.strftime("%Y-%m-%d") + "|" + df["direction"] + "|" + df["amount"].round(2).astype(str)
        + "|" + df["counterparty_inn"] + "|" + df["counterparty_name"] + "|" + df["purpose"]
    )
    rep = key.groupby(key).cumcount().astype(str)
    return (key + "|" + rep).map(lambda k: "t" + hashlib.sha1(k.encode("utf-8")).hexdigest()[:12])


def load_statement(
    path_or_df: str | Path | pd.DataFrame | BinaryIO | bytes,
    *,
    opening_balance: float | None = None,
    company_id: str | None = None,
) -> pd.DataFrame:
    warnings: list[str] = []
    quality: dict[str, Any] = {}

    if isinstance(path_or_df, pd.DataFrame):
        src = path_or_df.copy().reset_index(drop=True)
        src.attrs = {}
        mapping = _match_columns(src.columns)
        if "date" not in mapping:
            src = _find_header(pd.DataFrame([list(src.columns)] + src.astype(str).values.tolist()))
            mapping = _match_columns(src.columns)
    else:
        try:
            raw = _read_any(path_or_df)
        except Exception as exc:
            log.warning("statement read failed: %s", type(exc).__name__)
            empty = _empty_frame()
            empty.attrs.update(warnings=[f"Не удалось прочитать файл выписки ({type(exc).__name__})."],
                               quality={"rows_in": 0, "rows_out": 0}, opening_balance=opening_balance or 0.0,
                               company_id=company_id)
            return empty
        src = _find_header(raw) if len(raw) else pd.DataFrame()
        mapping = _match_columns(src.columns)

    if "company_id" in mapping and len(src):
        cids = src[mapping["company_id"]].astype(str).str.strip()
        uniq = [c for c in cids.unique() if c]
        if company_id is not None:
            src = src[cids == str(company_id)]
        elif len(uniq) > 1:
            company_id = uniq[0]
            warnings.append(f"В файле {len(uniq)} компаний; без company_id взята первая ({company_id}).")
            src = src[cids == company_id]
        elif uniq:
            company_id = uniq[0]

    quality["rows_in"] = int(len(src))
    quality["columns_mapped"] = {k: str(v) for k, v in mapping.items()}

    if "date" not in mapping or not ({"amount", "debit", "credit"} & mapping.keys()):
        warnings.append("Не найдены обязательные колонки даты и суммы — выписка пустая.")
        empty = _empty_frame()
        empty.attrs.update(warnings=warnings, quality=quality, opening_balance=opening_balance or 0.0,
                           company_id=company_id)
        return empty

    col = lambda k: src[mapping[k]] if k in mapping else pd.Series([""] * len(src), index=src.index)

    dates, fmts = parse_dates(col("date"))
    quality["date_formats"] = fmts

    if "amount" in mapping:
        amt = col("amount").map(parse_number).astype(float)
        dir_raw = col("direction").map(_parse_direction) if "direction" in mapping else pd.Series([None] * len(src), index=src.index)
        sign_dir = np.where(amt < 0, "out", "in")
        direction = dir_raw.where(dir_raw.notna(), sign_dir)
        conflict = dir_raw.notna() & (amt < 0) & (dir_raw == "in")
        if conflict.any():
            warnings.append(f"{int(conflict.sum())} строк: направление «in» при отрицательной сумме — взят модуль суммы.")
        amount = amt.abs()
    else:
        deb = col("debit").map(parse_number).astype(float).abs().fillna(0.0)
        cre = col("credit").map(parse_number).astype(float).abs().fillna(0.0)
        both = (deb > 0) & (cre > 0)
        base = src.copy()
        base["_amount"] = np.where(cre > 0, cre, deb)
        base["_dir"] = np.where(cre > 0, "in", "out")
        if both.any():
            extra = src[both].copy()
            extra["_amount"] = deb[both]
            extra["_dir"] = "out"
            base = pd.concat([base, extra])
            dates = pd.concat([dates, dates[both]])
        src = base
        amount = src["_amount"].astype(float).where(lambda v: v > 0)
        direction = pd.Series(src["_dir"].values, index=src.index)
        col = lambda k: src[mapping[k]] if k in mapping else pd.Series([""] * len(src), index=src.index)

    def _clean_text(s: pd.Series) -> pd.Series:
        return s.fillna("").astype(str).str.strip().replace({"nan": "", "None": "", "NaN": ""})

    inn = _clean_text(col("counterparty_inn")).str.replace(r"\.0$", "", regex=True).str.replace(r"\D", "", regex=True)
    out = pd.DataFrame({
        "date": dates.values,
        "amount": pd.to_numeric(amount, errors="coerce").values,
        "direction": pd.Series(direction).values,
        "counterparty_name": _clean_text(col("counterparty_name")).values,
        "counterparty_inn": inn.values,
        "purpose": _clean_text(col("purpose")).values,
        "balance_eod": col("balance_eod").map(parse_number).astype(float).values if "balance_eod" in mapping else np.nan,
        "source_id": _clean_text(col("source_id")).values if "source_id" in mapping else "",
    })

    bad = out["date"].isna() | out["amount"].isna() | (out["amount"] <= 0) | ~out["direction"].isin(["in", "out"])
    quality["dropped_invalid"] = int(bad.sum())
    if bad.any():
        warnings.append(f"Отброшено {int(bad.sum())} строк без даты/суммы или с нулевой суммой.")
    out = out[~bad].copy()
    out["row_order"] = np.arange(len(out))
    out = out.sort_values(["date", "row_order"], kind="stable").reset_index(drop=True)

    out, n_dup = _drop_duplicates(out)
    quality["duplicates_removed"] = n_dup
    if n_dup:
        warnings.append(f"Удалено {n_dup} дублирующихся операций.")

    out["signed_amount"] = np.where(out["direction"] == "in", out["amount"], -out["amount"])

    has_balance = bool(out["balance_eod"].notna().any())
    quality["has_balance"] = has_balance
    if not has_balance:
        ob = float(opening_balance) if opening_balance is not None else 0.0
        if opening_balance is None and len(out):
            warnings.append("В выписке нет остатков: стартовый остаток принят 0 ₽ (передайте opening_balance).")
    else:
        first_day = out["date"].min()
        day_rows = out[out["date"] == first_day]
        first_bal = day_rows["balance_eod"].dropna()
        if len(first_bal):
            ob = float(first_bal.iloc[-1] - day_rows["signed_amount"].sum())
        else:
            ob = float(opening_balance or 0.0)

    out["tx_id"] = _tx_ids(out) if len(out) else pd.Series(dtype=str)
    out = out[STANDARD_COLUMNS + ["source_id"]]
    out.attrs.update(warnings=warnings, quality=quality, opening_balance=ob, company_id=company_id)

    if len(out):
        daily = to_daily(out)
        mism = int(daily["mismatch"].sum())
        quality["balance_mismatch_days"] = mism
        quality["days"] = int(len(daily))
        quality["days_without_operations"] = int((daily["n_tx"] == 0).sum())
        longest = _longest_run(daily["n_tx"].values == 0)
        if mism:
            warnings.append(f"Остаток не сходится с суммой операций в {mism} дн. — вероятно, в выписке не хватает операций; "
                            "прогноз строится от последнего известного остатка.")
        if longest > 14:
            warnings.append(f"В выписке есть период {longest} дн. без операций — возможно, пропуск данных.")
        if (daily["balance"] < 0).any():
            warnings.append("В истории были дни с отрицательным остатком (овердрафт или ошибки выписки).")
        no_inn = float((out["counterparty_inn"].fillna("").astype(str).str.strip() == "").mean())
        no_purpose = float((out["purpose"].fillna("").astype(str).str.strip() == "").mean())
        quality["share_without_inn"], quality["share_without_purpose"] = round(no_inn, 3), round(no_purpose, 3)
        if no_inn >= 0.999:
            warnings.append("Ни у одной операции нет ИНН контрагента — клиентов и регулярные платежи узнаём только "
                            "по названиям, точность ниже.")
        if no_purpose >= 0.3:
            warnings.append(f"У {no_purpose:.0%} операций пустое назначение платежа — категории определены по "
                            "контрагенту и сумме и могут быть неточными.")
    quality["rows_out"] = int(len(out))
    log.info("statement loaded: rows_in=%d rows_out=%d dup=%d", quality["rows_in"], quality["rows_out"], n_dup)
    return out


def read_companies(path: str | Path) -> dict[str, pd.DataFrame]:
    raw = _find_header(_read_any(path))
    mapping = _match_columns(raw.columns)
    if "company_id" not in mapping:
        return {"": raw}
    col = mapping["company_id"]
    return {str(k): g.reset_index(drop=True) for k, g in raw.groupby(col, sort=True)}


def _empty_frame() -> pd.DataFrame:
    df = pd.DataFrame({c: pd.Series(dtype="object") for c in STANDARD_COLUMNS + ["source_id"]})
    df["date"] = pd.Series(dtype="datetime64[ns]")
    for c in ("amount", "signed_amount", "balance_eod"):
        df[c] = pd.Series(dtype=float)
    return df


def _longest_run(mask: np.ndarray) -> int:
    best = cur = 0
    for m in mask:
        cur = cur + 1 if m else 0
        best = max(best, cur)
    return best


def _drop_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if not len(df):
        return df, 0
    key_cols = ["date", "amount", "direction", "counterparty_inn", "counterparty_name", "purpose"]
    dup_mask = df.duplicated(subset=key_cols, keep="first")
    if not dup_mask.any():
        return df, 0
    if df["balance_eod"].isna().all():
        return df[~dup_mask].reset_index(drop=True), int(dup_mask.sum())

    signed = np.where(df["direction"] == "in", df["amount"], -df["amount"])
    tmp = df.assign(_s=signed, _dup=dup_mask)
    per_day = tmp.groupby("date").agg(net_all=("_s", "sum"), bal=("balance_eod", "last"))
    per_day["net_dedup"] = tmp[~tmp["_dup"]].groupby("date")["_s"].sum().reindex(per_day.index).fillna(0.0)
    per_day["prev_bal"] = per_day["bal"].shift(1)
    drop_days: set[pd.Timestamp] = set()
    for d, r in per_day.iterrows():
        if not tmp.loc[tmp["date"] == d, "_dup"].any():
            continue
        if pd.isna(r["bal"]) or pd.isna(r["prev_bal"]):
            drop_days.add(d)
            continue
        delta = r["bal"] - r["prev_bal"]
        if abs(r["net_dedup"] - delta) <= abs(r["net_all"] - delta):
            drop_days.add(d)
    remove = dup_mask & df["date"].isin(drop_days)
    return df[~remove].reset_index(drop=True), int(remove.sum())


def to_daily(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["inflow", "outflow", "net", "n_tx", "balance_reported", "balance", "mismatch"]
    if df is None or not len(df):
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], name="date"))
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.normalize()
    idx = pd.date_range(d["date"].min(), d["date"].max(), freq="D", name="date")
    g = d.groupby("date")
    by_dir = d.groupby(["date", "direction"])["amount"].sum().unstack(fill_value=0.0)
    daily = pd.DataFrame(index=idx)
    daily["inflow"] = (by_dir["in"] if "in" in by_dir else pd.Series(0.0, index=by_dir.index)).reindex(idx).fillna(0.0).astype(float)
    daily["outflow"] = (by_dir["out"] if "out" in by_dir else pd.Series(0.0, index=by_dir.index)).reindex(idx).fillna(0.0).astype(float)
    daily["net"] = daily["inflow"] - daily["outflow"]
    daily["n_tx"] = g.size().reindex(idx).fillna(0).astype(int)
    bal_rep = g["balance_eod"].last().reindex(idx) if "balance_eod" in d else pd.Series(np.nan, index=idx)
    daily["balance_reported"] = bal_rep.ffill()
    cum = daily["net"].cumsum()
    if bal_rep.notna().any():
        last_day = bal_rep.last_valid_index()
        anchor = float(bal_rep[last_day]) - float(cum[last_day])
    else:
        anchor = float(df.attrs.get("opening_balance", 0.0) or 0.0)
    daily["balance"] = anchor + cum
    known = bal_rep.dropna()
    mismatch = pd.Series(False, index=idx)
    if len(known) > 1:
        d_rep = known.diff()
        d_ops = cum.reindex(known.index).diff()
        tol = np.maximum(1.0, 1e-4 * known.abs())
        bad = ((d_rep - d_ops).abs() > tol) & d_rep.notna()
        mismatch.loc[bad[bad].index] = True
    daily["mismatch"] = mismatch.astype(bool)
    return daily[cols]
