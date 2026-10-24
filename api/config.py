from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = Path(__file__).resolve().parent


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on", "да")


def _secret(path: Path) -> str:
    env = os.getenv("JWT_SECRET")
    if env:
        return env
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return path.read_text().strip()
        s = secrets.token_urlsafe(48)
        path.write_text(s)
        return s
    except OSError:
        return secrets.token_urlsafe(48)


@dataclass
class Settings:
    use_stub_core: bool = field(default_factory=lambda: _bool("USE_STUB_CORE", False))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("API_DATA_DIR", API_DIR / "data")))
    database_url: str = ""
    jwt_secret: str = ""
    jwt_ttl_minutes: int = field(default_factory=lambda: int(os.getenv("JWT_TTL_MINUTES", "720")))
    users: str = field(default_factory=lambda: os.getenv("API_USERS", "demo:demo:S02"))
    max_upload_mb: float = field(default_factory=lambda: float(os.getenv("MAX_UPLOAD_MB", "20")))
    cors_origins: list[str] = field(default_factory=lambda: os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","))
    raw_dir: Path = field(default_factory=lambda: Path(os.getenv("RAW_DATA_DIR", ROOT / "data" / "raw")))
    synthetic_dir: Path = field(default_factory=lambda: Path(os.getenv("SYNTHETIC_DIR", ROOT / "data" / "synthetic")))
    mock_dir: Path = field(default_factory=lambda: ROOT / "docs" / "mock")
    core_path: Path = field(default_factory=lambda: Path(os.getenv("CORE_PATH", ROOT / "core")))
    default_horizon: int = 30
    registry_delay_days: int = field(default_factory=lambda: int(os.getenv("REGISTRY_DELAY_DAYS", "14")))
    public_predict: bool = field(default_factory=lambda: _bool("PUBLIC_PREDICT", True))
    n_sims: int = field(default_factory=lambda: int(os.getenv("CORE_N_SIMS", "2000")))
    demo_company: str = field(default_factory=lambda: os.getenv("DEMO_COMPANY", "S02"))
    demo_warmup: bool = field(default_factory=lambda: _bool("DEMO_WARMUP", False))
    demo_ttl_hours: int = field(default_factory=lambda: int(os.getenv("DEMO_TTL_HOURS", "24")))
    rate_limit_per_min: int = field(default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_MIN", "300")))
    rate_limit_heavy_per_min: int = field(default_factory=lambda: int(os.getenv("RATE_LIMIT_HEAVY_PER_MIN", "20")))
    trust_proxy: bool = field(default_factory=lambda: _bool("TRUST_PROXY", False))

    def __post_init__(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.database_url:
            self.database_url = os.getenv("DATABASE_URL", f"sqlite:///{self.data_dir / 'cashflow.db'}")
        if not self.jwt_secret:
            self.jwt_secret = _secret(self.data_dir / ".jwt_secret")

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings(**overrides) -> Settings:
    global _settings
    _settings = Settings(**overrides)
    return _settings
