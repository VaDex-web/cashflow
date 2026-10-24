from __future__ import annotations

import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor

_THREAD_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")


def _init_worker() -> None:
    for v in _THREAD_VARS:
        os.environ[v] = "1"
    try:
        from threadpoolctl import threadpool_limits

        threadpool_limits(1)
    except Exception:
        pass


def make_pool(workers: int) -> ProcessPoolExecutor:
    saved = {v: os.environ.get(v) for v in _THREAD_VARS}
    for v in _THREAD_VARS:
        os.environ[v] = "1"
    try:
        return ProcessPoolExecutor(max_workers=max(1, workers), mp_context=mp.get_context("spawn"),
                                   initializer=_init_worker)
    finally:
        for v, val in saved.items():
            if val is None:
                os.environ.pop(v, None)
            else:
                os.environ[v] = val
