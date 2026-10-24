from __future__ import annotations

from functools import lru_cache

import pandas as pd

from cashflow_core import build_state, load_statement
from datagen import generate_statement

FAST = {"n_sims": 400, "seed": 7}


@lru_cache(maxsize=8)
def base_df(days: int = 400, seed: int = 42) -> pd.DataFrame:
    return generate_statement(days=days, seed=seed)


@lru_cache(maxsize=8)
def base_state(days: int = 400, seed: int = 42, model: str = "ets"):
    return build_state(load_statement(base_df(days, seed)), [], 30, model=model, **FAST)


def last_date(df: pd.DataFrame) -> pd.Timestamp:
    return pd.to_datetime(df["date"]).max()
