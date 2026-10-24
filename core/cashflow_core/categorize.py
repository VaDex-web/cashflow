"""Категоризация операций (п.2 задания).

Трёхступенчатая схема:

1. **Правила** — регулярные выражения по назначению платежа и названию
   контрагента. Перед проверкой из текста вырезаются «хвосты» про НДС
   («в т.ч. НДС 20%», «Без НДС») — иначе любая оплата поставщику похожа на налог.
2. **Память контрагента** — если у ИНН/названия контрагента большинство операций
   уже уверенно размечено правилами, неразмеченные операции того же контрагента
   (например, с пустым назначением) получают ту же категорию.
3. **ML-запас** — TF-IDF (символьные n-граммы назначения и контрагента +
   направление + порядок суммы) и логистическая регрессия, обученные на
   уверенной разметке правил. Применяется к строкам, где правила не уверены.

Результат: колонки ``category`` (код из :data:`schema.CATEGORIES`),
``category_label``, ``category_confidence`` (0..1) и ``category_source``
(rule | counterparty | ml | default).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .log import get_logger
from .schema import CATEGORIES, CATEGORY_DIRECTIONS

log = get_logger(__name__)

_NDS_TAIL = re.compile(
    r"(в\s*т\.?\s*ч\.?\s*ндс.*$|в\s+том\s+числе\s+ндс.*$|сумма\s+[\d\s.,-]+\s*(руб\.?)?\s*(в\s*т\.?\s*ч|в\s+том).*$"
    r"|ндс\s+не\s+облагается\.?|без\s+налога\s*\(?ндс\)?\.?|без\s+ндс\.?|ндс\s+не\s+предусмотрен\w*\.?|ндс\s+нет\.?)"
)

#: Решения владельца, а не обязательства бизнеса: дивиденды, займы учредителя и их возврат, взносы в капитал.
#: Прогноз их не ожидает (владелец решает сам, когда и сколько), и отсрочку по ним не советует.
OWNER_FLOW_RE = re.compile(r"дивиденд|учредител|участник\w*\s+обществ|уставн\w*\s+капитал", re.IGNORECASE)


def owner_flow_mask(df: pd.DataFrame) -> pd.Series:
    """True для операций между бизнесом и его владельцем (по назначению или названию контрагента)."""
    if df is None or not len(df):
        return pd.Series(False, index=getattr(df, "index", None), dtype=bool)
    text = df["purpose"].fillna("").astype(str) + " " + df["counterparty_name"].fillna("").astype(str)
    return text.str.contains(OWNER_FLOW_RE)


# (категория, допустимые направления, regex, уверенность). Порядок = приоритет.
_RULES: list[tuple[str, tuple[str, ...], str, float]] = [
    ("bank_fees", ("out",), r"комисси\w*\s+(за|банка|по)|плата\s+за\s+(аренду\s+)?pos|pos-терминал|ведени\w*\s+счет"
                            r"|обслуживани\w*\s+(расчетного\s+)?счет|\bрко\b|тарифн\w*\s+план|пакет\s+услуг|sms-информ|смс-информ", 0.95),
    ("revenue", ("in",), r"эквайринг|\bсбп\b|qr-код|торгов\w*\s+выручк|инкасс|выручк|взнос\s+наличных", 0.97),
    ("transfers", ("in", "out"), r"собственн\w*\s+средств|между\s+(своими|собственными)\s+счет|на\s+(свой|собственный)\s+счет"
                                 r"|на\s+личн\w*\s+(счет|карту)\s*(предпринимател)?|перечислени\w*\s+остатка\s+денежных"
                                 r"|пополнени\w*\s+счета\s+(для\s+погашения|собственн)|взнос\s+в\s+уставный", 0.95),
    ("loans", ("in", "out"), r"\bзайм|\bзаем|\bзаём|\bкредит(?!ов\w*\s+организац)|\bссуд|лизинг|овердрафт|основн\w*\s+долг"
                             r"|\bтранш|уплата\s+процентов", 0.93),
    ("other", ("in", "out"), r"дивиденд|исполнительн\w*\s+лист|\bштраф|возврат\s+(платежа|ошибочн|денежных\s+средств|излишне)"
                             r"|страхов\w*\s+возмещени|субсиди|\bгрант|подотчет|под\s+отчет|материальн\w*\s+помощ", 0.9),
    ("taxes", ("out",), r"\bенп\b|единый\s+налоговый|налог|\bндфл|страхов\w*\s+взнос|\bусн\b|\bфнс\b|\bпени\b|\bкбк\b|\bесхн\b", 0.97),
    ("payroll", ("out",), r"заработн\w*\s+плат|зарплат|\bз/п\b|\bзп\b|оплата\s+труда|отпускн|\bпремии?\b|больничн|пособи"
                          r"|расчет\w*\s+при\s+увольнен", 0.96),
    ("payroll", ("out",), r"договор\w*\s+гпх|\bгпх\b|самозанят", 0.85),
    ("rent", ("out",), r"аренд|субаренд|найм\s+помещ", 0.94),
    ("utilities", ("out",), r"услуг\w*\s+связи|\bсвязь\b|интернет|телефон|водоснаб|водоотвед|электроэнерг|теплоснаб|тепловую\s+энерг"
                            r"|отоплени|газоснаб|вывоз\s+(тко|мусора|отход)|\bтко\b|коммунал|прав\w*\s+использования\s+по"
                            r"|подписк|облачн|хостинг|\bдомен|лицензи\w*\s+(на\s+)?(по|программ)", 0.92),
    ("revenue", ("in",), r"оплат|доплат|предоплат|расчет|аванс|перечислени\w*\s+денежных\s+средств\s+по\s+(договору|агентск)"
                         r"|по\s+сч(ету|\.)|по\s+упд|по\s+договору|гарантийн\w*\s+удержан|за\s+(товар|услуг|работ)", 0.9),
    ("suppliers", ("out",), r"оплат|по\s+сч(ету|\.)|по\s+упд|поставк|закупк|товар|услуг|пополнени\w*\s+(рекламного|лицевого)"
                            r"|расчетной\s+записи|предоплат|окончательный\s+расчет|подряд|материал|\bтмц\b", 0.88),
]
_COMPILED = [(c, d, re.compile(p), conf) for c, d, p, conf in _RULES]

_TAX_COUNTERPARTY = re.compile(r"казначейств|\bфнс\b|\bифнс\b|\bуфк\b.*фнс|налогов")

#: Уверенность, начиная с которой разметка правил считается «эталонной» для обучения ML.
STRONG = 0.85
#: Строки с уверенностью ниже этого порога пробуем улучшить памятью контрагента и ML.
WEAK = 0.7


def normalize_text(purpose: str, counterparty: str = "") -> str:
    """Нижний регистр, ё→е, без хвостов про НДС, без лишних пробелов."""
    s = f"{purpose or ''}".lower().replace("ё", "е")
    s = _NDS_TAIL.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _cp_key(inn: str, name: str) -> str:
    inn = (inn or "").strip()
    if inn:
        return "inn:" + inn
    n = re.sub(r"\d+", "#", (name or "").lower().replace("ё", "е")).strip()
    return "name:" + n if n else ""


def rule_category(purpose: str, counterparty_name: str, direction: str) -> tuple[str | None, float]:
    """Применить правила к одной операции. Возвращает (категория|None, уверенность)."""
    text = normalize_text(purpose)
    cp = (counterparty_name or "").lower().replace("ё", "е")
    if text:
        for cat, dirs, rx, conf in _COMPILED:
            if direction in dirs and rx.search(text):
                return cat, conf
    if direction == "out" and _TAX_COUNTERPARTY.search(cp):
        return "taxes", 0.9
    if direction == "in":
        return "revenue", 0.55  # большинство поступлений малого бизнеса — выручка
    return None, 0.0


def _amount_bucket(a: float) -> str:
    if not np.isfinite(a) or a <= 0:
        return "amt0"
    return f"amt{int(np.floor(np.log10(a) * 2))}"


def _ml_text(purpose: str, cp_name: str, direction: str, amount: float) -> str:
    cp = re.sub(r"[\d«»\"-]+", " ", (cp_name or "").lower().replace("ё", "е"))
    return f"zz{direction} {_amount_bucket(amount)} | {normalize_text(purpose)} | {cp}"


@dataclass
class Categorizer:
    """Обученный категоризатор: память контрагентов + ML-модель.

    Хранится в состоянии прогноза, чтобы новые операции в :func:`update_forecast`
    размечались без переобучения.
    """

    cp_memory: dict[tuple[str, str], tuple[str, float]] = field(default_factory=dict)
    model: Any = None
    classes: list[str] = field(default_factory=list)
    n_train: int = 0

    # ---------------------------------------------------------------- fitting
    def fit(self, df: pd.DataFrame, rule_cat: pd.Series, rule_conf: pd.Series, seed: int = 42) -> "Categorizer":
        strong = rule_conf >= STRONG
        keys = [_cp_key(i, n) for i, n in zip(df["counterparty_inn"], df["counterparty_name"])]
        tmp = pd.DataFrame({"k": keys, "dir": df["direction"].values, "cat": rule_cat.values, "strong": strong.values})
        mem: dict[tuple[str, str], tuple[str, float]] = {}
        for (k, d), g in tmp[tmp["strong"] & (tmp["k"] != "")].groupby(["k", "dir"]):
            vc = g["cat"].value_counts()
            share = float(vc.iloc[0] / vc.sum())
            if vc.sum() >= 3 and share >= 0.8:
                mem[(k, d)] = (str(vc.index[0]), share)
        self.cp_memory = mem

        y = rule_cat[strong].astype(str)
        if len(y) >= 30 and y.nunique() >= 2:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import make_pipeline

            texts = [_ml_text(p, n, d, a) for p, n, d, a in zip(
                df.loc[strong, "purpose"], df.loc[strong, "counterparty_name"], df.loc[strong, "direction"], df.loc[strong, "amount"])]
            # ограничиваем объём обучения, чтобы ядро оставалось быстрым
            if len(texts) > 6000:
                rs = np.random.default_rng(seed)
                sel = rs.choice(len(texts), 6000, replace=False)
                texts = [texts[i] for i in sel]
                y = y.iloc[sel]
            self.model = make_pipeline(
                TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=2, sublinear_tf=True, max_features=12000),
                LogisticRegression(max_iter=200, C=4.0, class_weight="balanced", tol=1e-3),
            )
            self.model.fit(texts, y.values)
            self.classes = list(self.model.classes_)
            self.n_train = len(texts)
        return self

    # ---------------------------------------------------------------- predict
    def predict_ml(self, purpose: list[str], names: list[str], dirs: list[str], amounts: list[float]) -> tuple[list[str | None], np.ndarray]:
        """ML-предсказание с маской допустимых направлений категории."""
        if self.model is None or not len(purpose):
            return [None] * len(purpose), np.zeros(len(purpose))
        texts = [_ml_text(p, n, d, a) for p, n, d, a in zip(purpose, names, dirs, amounts)]
        proba = self.model.predict_proba(texts)
        allowed = np.array([[d in CATEGORY_DIRECTIONS.get(c, ("in", "out")) for c in self.classes] for d in dirs])
        proba = np.where(allowed, proba, 0.0)
        s = proba.sum(axis=1, keepdims=True)
        proba = np.divide(proba, s, out=np.zeros_like(proba), where=s > 0)
        idx = proba.argmax(axis=1)
        conf = proba[np.arange(len(idx)), idx]
        cats = [self.classes[i] if c > 0 else None for i, c in zip(idx, conf)]
        return cats, conf

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Разметить операции (правила → память контрагента → ML)."""
        out = df.copy()
        out.attrs = {}
        if not len(out):
            for c, v in (("category", ""), ("category_label", ""), ("category_confidence", 0.0), ("category_source", "")):
                out[c] = pd.Series(dtype=type(v))
            return out
        res = [rule_category(p, n, d) for p, n, d in zip(out["purpose"], out["counterparty_name"], out["direction"])]
        cat = pd.Series([r[0] for r in res], index=out.index, dtype=object)
        conf = pd.Series([r[1] for r in res], index=out.index, dtype=float)
        src = pd.Series(np.where(conf >= 0.85, "rule", np.where(cat.notna(), "default", "")), index=out.index, dtype=object)

        weak = conf < WEAK
        if weak.any() and self.cp_memory:
            for i in out.index[weak]:
                k = _cp_key(out.at[i, "counterparty_inn"], out.at[i, "counterparty_name"])
                hit = self.cp_memory.get((k, out.at[i, "direction"]))
                if hit:
                    cat.at[i], conf.at[i], src.at[i] = hit[0], round(0.85 * hit[1], 3), "counterparty"
        weak = conf < WEAK
        if weak.any() and self.model is not None:
            sub = out[weak]
            mcats, mconf = self.predict_ml(sub["purpose"].tolist(), sub["counterparty_name"].tolist(),
                                           sub["direction"].tolist(), sub["amount"].astype(float).tolist())
            for i, mc, mp in zip(sub.index, mcats, mconf):
                if mc is not None and mp > conf.at[i]:
                    cat.at[i], conf.at[i], src.at[i] = mc, round(float(mp) * 0.9, 3), "ml"
        miss = cat.isna()
        cat[miss] = "other"
        conf[miss] = 0.3
        src[miss] = "default"
        out["category"] = cat.astype(str)
        out["category_label"] = out["category"].map(CATEGORIES).fillna(CATEGORIES["other"])
        out["category_confidence"] = conf.round(3)
        out["category_source"] = src
        return out


def fit_categorizer(df: pd.DataFrame, seed: int = 42) -> Categorizer:
    """Обучить категоризатор на выписке (разметка правилами → память → ML)."""
    res = [rule_category(p, n, d) for p, n, d in zip(df["purpose"], df["counterparty_name"], df["direction"])]
    rule_cat = pd.Series([r[0] for r in res], index=df.index, dtype=object)
    rule_conf = pd.Series([r[1] for r in res], index=df.index, dtype=float)
    cz = Categorizer().fit(df, rule_cat, rule_conf, seed=seed)
    log.info("categorizer fitted: train_rows=%d memory=%d", cz.n_train, len(cz.cp_memory))
    return cz


def categorize(df: pd.DataFrame, categorizer: Categorizer | None = None) -> pd.DataFrame:
    """Добавить колонки ``category``, ``category_label``, ``category_confidence``, ``category_source``.

    Args:
        df: результат :func:`load_statement`.
        categorizer: готовый категоризатор (если None — обучается на этих же данных).
    """
    if df is None or not len(df):
        out = df.copy() if df is not None else pd.DataFrame()
        for c in ("category", "category_label", "category_source"):
            out[c] = pd.Series(dtype=object)
        out["category_confidence"] = pd.Series(dtype=float)
        return out
    cz = categorizer or fit_categorizer(df)
    out = cz.transform(df)
    # В attrs только лёгкие данные: pandas глубоко копирует attrs при каждой операции.
    out.attrs = dict(df.attrs)
    return out


# --------------------------------------------------------------------------- evaluation
def classification_metrics(y_true: list[str] | pd.Series, y_pred: list[str] | pd.Series) -> dict[str, Any]:
    """Accuracy, macro-F1 и F1 по классам."""
    from sklearn.metrics import accuracy_score, f1_score

    yt, yp = list(map(str, y_true)), list(map(str, y_pred))
    labels = sorted(set(yt))
    per = f1_score(yt, yp, labels=labels, average=None, zero_division=0)
    return {
        "n": len(yt),
        "accuracy": round(float(accuracy_score(yt, yp)), 4),
        "macro_f1": round(float(f1_score(yt, yp, labels=labels, average="macro", zero_division=0)), 4),
        "weighted_f1": round(float(f1_score(yt, yp, labels=labels, average="weighted", zero_division=0)), 4),
        "f1_by_class": {l: round(float(v), 4) for l, v in zip(labels, per)},
    }


def evaluate_categorization(df: pd.DataFrame, true_col: str | None = None, seed: int = 42,
                            holdout_share: float = 0.3) -> dict[str, Any]:
    """Честная оценка качества категоризации.

    * ``coverage`` — доля операций, уверенно размеченных правилами;
    * ``ml_holdout`` — ML обучается на 70% уверенной разметки, проверяется на 30%,
      **у которых назначение платежа скрыто** (имитация пустого назначения): так
      оценивается именно запасной механизм, а не повтор правил;
    * ``vs_truth`` — если есть колонка с истинной категорией, полный пайплайн против неё.
    """
    from sklearn.model_selection import train_test_split

    res = [rule_category(p, n, d) for p, n, d in zip(df["purpose"], df["counterparty_name"], df["direction"])]
    rc = pd.Series([r[0] for r in res], index=df.index, dtype=object)
    rconf = pd.Series([r[1] for r in res], index=df.index, dtype=float)
    out: dict[str, Any] = {"n_rows": int(len(df)), "coverage_strong_rules": round(float((rconf >= STRONG).mean()), 4)}
    strong_idx = df.index[rconf >= STRONG]
    y = rc[strong_idx].astype(str)
    if len(strong_idx) >= 50 and y.nunique() >= 2:
        strat = y if y.value_counts().min() >= 2 else None
        tr, te = train_test_split(strong_idx, test_size=holdout_share, random_state=seed, stratify=strat)
        cz = Categorizer().fit(df.loc[tr], rc[tr], rconf[tr], seed=seed)
        masked = df.loc[te].copy()
        masked["purpose"] = ""
        pred = cz.transform(masked)["category"]
        out["ml_holdout_masked_purpose"] = classification_metrics(y[te], pred)
    if true_col and true_col in df.columns:
        pred = categorize(df)["category"]
        out["vs_truth"] = classification_metrics(df[true_col], pred)
    return out
