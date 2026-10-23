"""Пул процессов без «драки» потоков.

Бустинг и numpy по умолчанию запускают по потоку на ядро. Если в пуле N процессов
на N ядрах, потоков становится N² и всё замедляется в десятки раз. Поэтому каждый
рабочий процесс ограничен одним потоком, а процессы создаются через ``spawn``
(``fork`` после запуска потоков библиотек может зависнуть).
"""
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
    except Exception:  # noqa: BLE001
        pass


def make_pool(workers: int) -> ProcessPoolExecutor:
    """ProcessPoolExecutor с одним потоком на процесс и стартом через spawn."""
    saved = {v: os.environ.get(v) for v in _THREAD_VARS}
    for v in _THREAD_VARS:
        os.environ[v] = "1"  # дочерние процессы унаследуют ограничение с самого старта
    try:
        return ProcessPoolExecutor(max_workers=max(1, workers), mp_context=mp.get_context("spawn"),
                                   initializer=_init_worker)
    finally:
        for v, val in saved.items():
            if val is None:
                os.environ.pop(v, None)
            else:
                os.environ[v] = val
