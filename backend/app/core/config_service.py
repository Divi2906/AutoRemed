"""Runtime configuration persisted in the ``config`` table."""
from __future__ import annotations

import copy
from typing import Any

from .activity import ActivityLog
from .db import Database
from .errors import ValidationFailed
from .util import dumps, loads, utcnow

METRICS = ("cpu", "memory", "disk")

DEFAULTS: dict[str, Any] = {
    "thresholds": {
        "cpu": {"warning": 75.0, "critical": 90.0},
        "memory": {"warning": 80.0, "critical": 90.0},
        "disk": {"warning": 85.0, "critical": 95.0},
    },
    "mode": "autonomous",
    "monitoring": {"interval_seconds": 5.0, "enabled": True},
    # Consecutive violating samples required before an incident is raised, per environment.
    # Real host defaults to 3 so transient spikes do not create incidents; the simulation is
    # deterministic so 1 is used.
    "consecutive_violations": {"real_host": 3, "simulation": 1},
    "ranker": "rule_based",
}

MODES = ("autonomous", "approval")
MIN_INTERVAL = 1.0
MAX_INTERVAL = 3600.0


class ConfigService:
    def __init__(self, db: Database, activity: ActivityLog):
        self.db = db
        self.activity = activity

    # ------------------------------------------------------------------ generic
    def get(self, key: str) -> Any:
        row = self.db.query_one("SELECT value FROM config WHERE key = ?", (key,))
        if row is None:
            return copy.deepcopy(DEFAULTS[key])
        return loads(row["value"])

    def _set(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO config (key, value, updated_at) VALUES (?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, dumps(value), utcnow()),
        )

    def all(self) -> dict[str, Any]:
        return {k: self.get(k) for k in DEFAULTS}

    # ------------------------------------------------------------------ thresholds
    def thresholds(self) -> dict[str, dict[str, float]]:
        stored = self.get("thresholds")
        merged = copy.deepcopy(DEFAULTS["thresholds"])
        for m in METRICS:
            merged[m].update(stored.get(m, {}))
        return merged

    def set_thresholds(self, new: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
        current = self.thresholds()
        for metric, vals in new.items():
            if metric not in METRICS:
                raise ValidationFailed(f"unknown metric '{metric}'")
            current[metric].update({k: float(v) for k, v in vals.items() if v is not None})
        for metric in METRICS:
            w, c = current[metric]["warning"], current[metric]["critical"]
            if not (0 < w < c <= 100):
                raise ValidationFailed(
                    f"{metric}: thresholds must satisfy 0 < warning < critical <= 100 (got {w}, {c})"
                )
        old = self.thresholds()
        self._set("thresholds", current)
        self.activity.log(
            "config_changed",
            "Thresholds updated",
            action="update_thresholds",
            status="ok",
            details={"old": old, "new": current},
        )
        return current

    # ------------------------------------------------------------------ mode
    def mode(self) -> str:
        return self.get("mode")

    def set_mode(self, mode: str) -> str:
        if mode not in MODES:
            raise ValidationFailed(f"mode must be one of {MODES}")
        old = self.mode()
        self._set("mode", mode)
        self.activity.log(
            "config_changed",
            f"Operating mode changed: {old} -> {mode}",
            action="set_mode",
            status="ok",
            details={"old": old, "new": mode},
        )
        return mode

    # ------------------------------------------------------------------ monitoring
    def monitoring(self) -> dict[str, Any]:
        merged = copy.deepcopy(DEFAULTS["monitoring"])
        merged.update(self.get("monitoring"))
        return merged

    def set_monitoring(self, *, interval_seconds: float | None = None, enabled: bool | None = None,
                       log: bool = True) -> dict[str, Any]:
        cur = self.monitoring()
        if interval_seconds is not None:
            if not (MIN_INTERVAL <= interval_seconds <= MAX_INTERVAL):
                raise ValidationFailed(
                    f"interval_seconds must be between {MIN_INTERVAL} and {MAX_INTERVAL}"
                )
            cur["interval_seconds"] = float(interval_seconds)
        if enabled is not None:
            cur["enabled"] = bool(enabled)
        self._set("monitoring", cur)
        if log and interval_seconds is not None:
            self.activity.log(
                "config_changed",
                f"Monitoring interval set to {cur['interval_seconds']}s",
                action="set_monitoring_interval",
                status="ok",
            )
        return cur

    def consecutive_required(self, environment: str) -> int:
        stored = self.get("consecutive_violations")
        return max(1, int(stored.get(environment, DEFAULTS["consecutive_violations"][environment])))

    def set_consecutive(self, environment: str, n: int) -> None:
        if n < 1 or n > 20:
            raise ValidationFailed("consecutive violations must be between 1 and 20")
        cur = self.get("consecutive_violations")
        cur[environment] = int(n)
        self._set("consecutive_violations", cur)
        self.activity.log(
            "config_changed",
            f"Consecutive violations for {environment} set to {n}",
            action="set_consecutive_violations",
            status="ok",
        )
