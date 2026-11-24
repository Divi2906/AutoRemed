"""Metric sources. The two environments are kept strictly separate:

* ``RealHostSource``  - read-only psutil readings of the machine AutoRemed runs on.
* ``SimulatedSource`` - reads the application's own simulated state.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from ..core.util import ENV_REAL, ENV_SIM, utcnow
from ..simulation.state import SimulationState

logger = logging.getLogger("autoremed.sources")


@dataclass
class Snapshot:
    environment: str
    ts: str
    cpu: float | None
    memory: float | None
    disk: float | None
    service_state: str | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "environment": self.environment, "ts": self.ts, "cpu": self.cpu, "memory": self.memory,
            "disk": self.disk, "service_state": self.service_state, "errors": list(self.errors),
        }


class MetricSource(Protocol):
    environment: str

    def collect(self) -> Snapshot: ...


class RealHostSource:
    """Read-only host metrics via psutil. Never writes to or repairs the host."""

    environment = ENV_REAL

    def __init__(self, disk_path: str | None = None, psutil_module: Any = None, cache_seconds: float = 1.0):
        if psutil_module is None:
            import psutil as psutil_module  # local import keeps tests able to inject a fake
        self._psutil = psutil_module
        self._disk_path = disk_path or os.path.abspath(os.sep)
        self._cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._last: Snapshot | None = None
        self._last_at = 0.0
        try:
            self._psutil.cpu_percent(interval=None)  # prime: first call is always 0.0
        except Exception:
            logger.exception("psutil priming failed")

    def collect(self) -> Snapshot:
        with self._lock:
            now = time.monotonic()
            if self._last is not None and (now - self._last_at) < self._cache_seconds:
                return self._last
            errors: list[str] = []
            cpu = self._safe(lambda: self._psutil.cpu_percent(interval=None), "cpu", errors)
            mem = self._safe(lambda: self._psutil.virtual_memory().percent, "memory", errors)
            disk = self._safe(lambda: self._psutil.disk_usage(self._disk_path).percent, "disk", errors)
            snap = Snapshot(ENV_REAL, utcnow(), cpu, mem, disk, None, errors)
            self._last, self._last_at = snap, now
            return snap

    @staticmethod
    def _safe(fn: Callable[[], float], name: str, errors: list[str]) -> float | None:
        try:
            return round(float(fn()), 2)
        except Exception as exc:  # unavailable metric must not break collection
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            logger.warning("real host metric '%s' unavailable: %s", name, exc)
            return None


class SimulatedSource:
    environment = ENV_SIM

    def __init__(self, sim: SimulationState):
        self.sim = sim

    def collect(self) -> Snapshot:
        s = self.sim.snapshot()
        return Snapshot(ENV_SIM, utcnow(), s["cpu"], s["memory"], s["disk"], s["service_state"])
