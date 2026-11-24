"""Threshold evaluation: pure functions, no I/O."""
from __future__ import annotations

from typing import Any

METRICS = ("cpu", "memory", "disk")
_ORDER = {"ok": 0, "warning": 1, "critical": 2}


def classify(value: float | None, warning: float, critical: float) -> str:
    if value is None:
        return "unknown"
    if value >= critical:
        return "critical"
    if value >= warning:
        return "warning"
    return "ok"


def classify_service(state: str | None) -> str:
    return {"running": "ok", "degraded": "warning", "failed": "critical"}.get(state or "", "unknown")


def metric_statuses(snapshot: dict[str, Any], thresholds: dict[str, dict[str, float]]) -> dict[str, str]:
    out = {
        m: classify(snapshot.get(m), thresholds[m]["warning"], thresholds[m]["critical"]) for m in METRICS
    }
    if snapshot.get("service_state") is not None:
        out["service"] = classify_service(snapshot["service_state"])
    return out


def overall(statuses: dict[str, str]) -> str:
    known = [s for s in statuses.values() if s in _ORDER]
    if not known:
        return "unknown"
    return max(known, key=lambda s: _ORDER[s])
