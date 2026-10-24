from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .calendar_ru import calendar_features


def _window_mean(c: np.ndarray, a: int, b: int) -> float:
    a, b = max(a, 0), min(b, len(c) - 1)
    if b <= a:
        return np.nan
    return float((c[b] - c[a]) / (b - a))


def _future_index(y: pd.Series, horizon: int) -> pd.DatetimeIndex:
    return pd.date_range(y.index[-1] + pd.Timedelta(days=1), periods=horizon, freq="D")


class NaiveRepeat:
    name = "naive"

    def __init__(self, window: int = 28) -> None:
        self.window = window

    def fit(self, y: pd.Series) -> "NaiveRepeat":
        return self

    def forecast(self, y: pd.Series, horizon: int) -> np.ndarray:
        if not len(y):
            return np.zeros(horizon)
        w = min(self.window, len(y))
        last = y.values[-w:]
        return np.array([last[k % w] for k in range(horizon)], dtype=float)


@dataclass
class SeasonalProfile:
    halflife: float = 20.0
    profile_days: int = 182
    use_yoy: bool = True
    yoy_shrink: float = 0.8
    yoy_max: float = 5.0
    yoy_eps_share: float = 0.0
    name: str = "ets"

    def fit(self, y: pd.Series) -> "SeasonalProfile":
        return self

    @staticmethod
    def _types(idx: pd.DatetimeIndex) -> pd.DataFrame:
        cf = calendar_features(idx)
        return cf[["dow", "is_business_day", "after_break"]]

    def _factors(self, y: pd.Series) -> tuple[dict[Any, float], float]:
        rec = y.iloc[-self.profile_days:]
        t = self._types(rec.index)
        bd = t["is_business_day"].values == 1
        base = float(rec.values[bd].mean()) if bd.any() else float(rec.values.mean())
        if not np.isfinite(base) or base <= 0:
            return {}, 0.0
        f: dict[Any, float] = {"nb": float(rec.values[~bd].mean() / base) if (~bd).any() else 0.0}
        for dow in range(7):
            for ab in (0, 1):
                m = bd & (t["dow"].values == dow) & (t["after_break"].values == ab)
                if m.sum() >= 4:
                    f[(dow, ab)] = float(rec.values[m].mean() / base)
            m = bd & (t["dow"].values == dow)
            f[dow] = float(rec.values[m].mean() / base) if m.sum() >= 3 else 1.0
        ab_m = bd & (t["after_break"].values == 1)
        f["ab"] = float(rec.values[ab_m].mean() / base) if ab_m.sum() >= 3 else 1.0
        return f, base

    @classmethod
    def _factor_vec(cls, f: dict[Any, float], types: np.ndarray) -> np.ndarray:
        table = np.array([cls._factor(f, dow, bd, ab) for bd in (0, 1) for dow in range(7) for ab in (0, 1)])
        t = types.astype(int)
        return table[t[:, 1] * 14 + t[:, 0] * 2 + t[:, 2]]

    @staticmethod
    def _factor(f: dict[Any, float], dow: int, bd: int, ab: int) -> float:
        if not bd:
            return f.get("nb", 0.0)
        return f.get((dow, ab), f.get(dow, 1.0) * (f.get("ab", 1.0) if ab else 1.0))

    def forecast(self, y: pd.Series, horizon: int) -> np.ndarray:
        if len(y) < 7 or y.values.sum() <= 0:
            return np.full(horizon, float(y.mean()) if len(y) else 0.0)
        f, _ = self._factors(y)
        if not f:
            return np.zeros(horizon)
        hist = y.iloc[-365:]
        t = self._types(hist.index)
        fac = self._factor_vec(f, t.values)
        bdm = t["is_business_day"].values == 1
        des = np.where(fac > 0.05, hist.values / np.maximum(fac, 0.05), np.nan)[bdm]
        des = des[np.isfinite(des)]
        if not len(des):
            level = float(hist.mean())
        else:
            w = 0.5 ** (np.arange(len(des))[::-1] / self.halflife)
            level = float(np.sum(w * des) / np.sum(w))
        fut = _future_index(y, horizon)
        tf = self._types(fut)
        pred = level * self._factor_vec(f, tf.values)
        if self.use_yoy and len(y) >= 400:
            c = np.concatenate([[0.0], np.cumsum(y.values)])
            n = len(y)
            base_ly = _window_mean(c, n - 364 - 28, n - 364)
            eps = self.yoy_eps_share * float(np.mean(y.values[-364:]))
            if np.isfinite(base_ly) and base_ly + eps > 0:
                for k in range(horizon):
                    j = n + k - 364
                    tgt = _window_mean(c, j - 3, j + 4)
                    if np.isfinite(tgt):
                        r = float(np.clip((tgt + eps) / (base_ly + eps), 1 / self.yoy_max, self.yoy_max)) ** self.yoy_shrink
                        pred[k] *= r
                if level <= 0 and eps > 0:
                    for k in range(horizon):
                        j = n + k - 364
                        tgt = _window_mean(c, j - 3, j + 4)
                        if np.isfinite(tgt):
                            pred[k] = max(pred[k], tgt * self.yoy_shrink)
        return np.maximum(pred, 0.0)


@dataclass
class GBMFlow:
    leads: tuple[int, ...] = (1, 7, 14, 21, 30)
    seed: int = 42
    name: str = "gbm"
    model: Any = None
    max_lead: int = 30
    _cols: Any = None
    _fallback: SeasonalProfile = field(default_factory=SeasonalProfile)

    def _features(self, y_vals: np.ndarray, c: np.ndarray, idx: pd.DatetimeIndex, t_pos: np.ndarray,
                  o_pos: np.ndarray, cal: pd.DataFrame) -> np.ndarray:
        rows = []
        for t, o in zip(t_pos, o_pos):
            l7 = _window_mean(c, o - 6, o + 1)
            l28 = _window_mean(c, o - 27, o + 1)
            l91 = _window_mean(c, o - 90, o + 1)
            yoy = _window_mean(c, t - 364 - 3, t - 364 + 4)
            yoy_base = _window_mean(c, o - 364 - 27, o - 364 + 1)
            ratio = l28 / yoy_base if np.isfinite(yoy_base) and yoy_base > 0 else np.nan
            rows.append([t - o, l7, l28, l91, yoy, ratio, yoy * ratio if np.isfinite(ratio) else np.nan])
        base = np.array(rows, dtype=float)
        calv = cal.iloc[t_pos][["dow", "dom", "month", "days_to_month_end", "is_business_day", "after_break",
                                "before_break", "is_holiday", "week_of_month"]].values.astype(float)
        return np.hstack([base, calv])

    def fit(self, y: pd.Series) -> "GBMFlow":
        from sklearn.ensemble import HistGradientBoostingRegressor

        n = len(y)
        if n < 120 or y.values.sum() <= 0:
            self.model = None
            return self
        ext_idx = pd.date_range(y.index[0], y.index[-1] + pd.Timedelta(days=self.max_lead + 5), freq="D")
        cal = calendar_features(ext_idx)
        c = np.concatenate([[0.0], np.cumsum(y.values)])
        t_list, o_list = [], []
        for k in self.leads:
            t = np.arange(28 + k, n)
            t_list.append(t)
            o_list.append(t - k)
        t_pos, o_pos = np.concatenate(t_list), np.concatenate(o_list)
        X = self._features(y.values, c, ext_idx, t_pos, o_pos, cal)
        target = y.values[t_pos]
        self._cols = np.array([np.unique(col[np.isfinite(col)]).size >= 2 for col in X.T])
        X = X[:, self._cols]
        self.model = HistGradientBoostingRegressor(
            loss="poisson", learning_rate=0.1, max_iter=100, max_leaf_nodes=15, min_samples_leaf=30,
            l2_regularization=1.0, random_state=self.seed)
        try:
            self.model.fit(X, np.maximum(target, 0.0))
        except ValueError:
            self.model = None
        return self

    def forecast(self, y: pd.Series, horizon: int) -> np.ndarray:
        if self.model is None:
            return self._fallback.forecast(y, horizon)
        n = len(y)
        ext_idx = pd.date_range(y.index[0], y.index[-1] + pd.Timedelta(days=horizon + 5), freq="D")
        cal = calendar_features(ext_idx)
        c = np.concatenate([[0.0], np.cumsum(y.values)])
        t_pos = np.arange(n, n + horizon)
        o_pos = np.full(horizon, n - 1)
        X = self._features(y.values, c, ext_idx, t_pos, o_pos, cal)
        X[:, 0] = np.minimum(X[:, 0], self.max_lead)
        return np.maximum(self.model.predict(X[:, self._cols]), 0.0)


MODEL_FACTORIES = {
    "naive": lambda seed=42: NaiveRepeat(),
    "ets": lambda seed=42: SeasonalProfile(),
    "gbm": lambda seed=42: GBMFlow(seed=seed),
}


def error_paths(y: pd.Series, model_name: str, horizon: int, *, n_origins: int = 30, step: int = 7,
                seed: int = 42, refit_every: int = 182, y_true: pd.Series | None = None
                ) -> tuple[np.ndarray, list[pd.Timestamp]]:
    n = len(y)
    last_origin = n - 1 - horizon
    origins = [last_origin - step * j for j in range(n_origins)]
    origins = [o for o in origins if o >= 56]
    paths, used = [], []
    model = None
    fitted_at = None
    for o in sorted(origins):
        ctx = y.iloc[: o + 1]
        if model is None or model_name != "gbm" or (fitted_at is not None and o - fitted_at >= refit_every):
            model = MODEL_FACTORIES[model_name](seed).fit(ctx)
            fitted_at = o
        pred = model.forecast(ctx, horizon)
        fact = (y_true if y_true is not None else y).values[o + 1: o + 1 + horizon]
        paths.append(fact - pred)
        used.append(y.index[o])
    if not paths:
        return np.zeros((0, horizon)), []
    return np.vstack(paths), used
