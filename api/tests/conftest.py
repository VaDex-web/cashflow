"""Общие фикстуры: отдельная временная база на тест, ядро-заглушка или настоящее cashflow_core."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
SYN = ROOT / "data" / "synthetic"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _core_path() -> Path:
    return Path(os.getenv("CORE_PATH", ROOT / "core"))


def core_available() -> bool:
    p = _core_path()
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))
    try:
        import cashflow_core  # noqa: F401, PLC0415
        return True
    except ImportError:
        return False


def make_client(tmp_path: Path, stub: bool, **overrides) -> TestClient:
    from api import core_adapter, db, services
    from api.config import reset_settings
    from api.main import create_app

    reset_settings(use_stub_core=stub, data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'test.db'}",
                   jwt_secret="test-secret-for-pytest-only-0123456789abcdef", users="demo:demo:S02,other:other", n_sims=400, core_path=_core_path(), **overrides)
    core_adapter.reset_core()
    services.reset_cache()
    db.init_db()
    return TestClient(create_app())


def login(client: TestClient, user: str = "demo", password: str | None = None) -> dict[str, str]:
    r = client.post("/api/auth/login", json={"username": user, "password": password or user})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def stub(tmp_path):
    with make_client(tmp_path, stub=True) as c:
        yield c


@pytest.fixture()
def real(tmp_path):
    if not core_available():
        pytest.skip("cashflow_core недоступен (укажите CORE_PATH)")
    with make_client(tmp_path, stub=False) as c:
        yield c


@pytest.fixture()
def auth(stub):
    return login(stub)
