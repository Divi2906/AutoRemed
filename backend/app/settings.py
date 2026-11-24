"""Process-level settings, read from environment variables.

Runtime-tunable configuration (thresholds, mode, monitoring interval) lives in the
database via ``core.config_service`` — these are only bootstrap settings.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent

# Hard safety cap. Never configurable: a remediation workflow may execute at most
# this many times (initial attempt included).
MAX_ATTEMPTS = 3


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_path: str = str(BASE_DIR / "data" / "autoremed.db")
    autostart_monitoring: bool = True
    # Pause between workflow phases so the dashboard can show progress. 0 in tests.
    step_delay_seconds: float = 1.5
    # Run remediation workflows inline (deterministic tests) instead of in a pool.
    sync_dispatch: bool = False
    log_level: str = "INFO"
    frontend_dist: str = str(REPO_DIR / "frontend" / "dist")
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    metrics_retention: int = 5000
    host_disk_path: str | None = None
    worker_threads: int = 8

    @classmethod
    def from_env(cls) -> "Settings":
        d = cls()
        return cls(
            db_path=os.environ.get("AUTOREMED_DB_PATH", d.db_path),
            autostart_monitoring=_bool("AUTOREMED_AUTOSTART_MONITORING", d.autostart_monitoring),
            step_delay_seconds=float(os.environ.get("AUTOREMED_STEP_DELAY", d.step_delay_seconds)),
            sync_dispatch=_bool("AUTOREMED_SYNC_DISPATCH", d.sync_dispatch),
            log_level=os.environ.get("AUTOREMED_LOG_LEVEL", d.log_level).upper(),
            frontend_dist=os.environ.get("AUTOREMED_FRONTEND_DIST", d.frontend_dist),
            cors_origins=tuple(
                o.strip()
                for o in os.environ.get("AUTOREMED_CORS_ORIGINS", ",".join(d.cors_origins)).split(",")
                if o.strip()
            ),
            metrics_retention=int(os.environ.get("AUTOREMED_METRICS_RETENTION", d.metrics_retention)),
            host_disk_path=os.environ.get("AUTOREMED_HOST_DISK_PATH") or None,
            worker_threads=int(os.environ.get("AUTOREMED_WORKER_THREADS", d.worker_threads)),
        )
