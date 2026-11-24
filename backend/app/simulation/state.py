"""Simulated environment state.

This is the ONLY state that fault injection and (simulated) remediation may modify.
It is persisted to SQLite so it survives restarts, and guarded by a lock so concurrent
remediation workflows on different metrics cannot corrupt each other.

``epoch`` increments on every reset. Executors capture the epoch before acting and their
writes are rejected if a reset happened in between (no stale write can dirty a clean state).
"""
from __future__ import annotations

import copy
import threading
from typing import Any

from ..core.db import Database
from ..core.errors import ValidationFailed
from ..core.util import dumps, loads, utcnow

BASELINE: dict[str, Any] = {"cpu": 22.0, "memory": 41.0, "disk": 58.0, "service_state": "running"}
FAULT_PRESETS: dict[str, Any] = {"cpu": 96.0, "memory": 94.0, "disk": 97.0, "service": "failed"}
FAULTS = ("cpu", "memory", "disk", "service")
SERVICE_STATES = ("running", "degraded", "failed")
NUMERIC = ("cpu", "memory", "disk")


def _clamp(v: float) -> float:
    return round(max(0.0, min(100.0, float(v))), 2)


class StaleEpoch(Exception):
    """The simulation was reset while an action was in flight."""


class SimulationState:
    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.RLock()
        self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self) -> None:
        row = self.db.query_one("SELECT * FROM sim_state WHERE id = 1")
        if row is None:
            self._state = copy.deepcopy(BASELINE)
            self._epoch = 0
            self._control: dict[str, Any] = {"plans": {}}
            self._persist()
        else:
            self._state = {
                "cpu": row["cpu"], "memory": row["memory"], "disk": row["disk"],
                "service_state": row["service_state"],
            }
            self._epoch = row["epoch"]
            self._control = loads(row["control_json"], {"plans": {}})
            self._control.setdefault("plans", {})

    def _persist(self) -> None:
        self.db.execute(
            "INSERT INTO sim_state (id, cpu, memory, disk, service_state, epoch, control_json, updated_at)"
            " VALUES (1,?,?,?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET cpu=excluded.cpu, memory=excluded.memory, disk=excluded.disk,"
            " service_state=excluded.service_state, epoch=excluded.epoch, control_json=excluded.control_json,"
            " updated_at=excluded.updated_at",
            (self._state["cpu"], self._state["memory"], self._state["disk"], self._state["service_state"],
             self._epoch, dumps(self._control), utcnow()),
        )

    # ------------------------------------------------------------------ reads
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {**self._state, "epoch": self._epoch}

    @property
    def epoch(self) -> int:
        with self._lock:
            return self._epoch

    # ------------------------------------------------------------------ writes
    def _check_epoch(self, epoch: int | None) -> None:
        if epoch is not None and epoch != self._epoch:
            raise StaleEpoch("simulation was reset during the action")

    def inject_fault(self, fault: str, value: float | str | None = None) -> dict[str, Any]:
        if fault not in FAULTS:
            raise ValidationFailed(f"unknown fault '{fault}' (expected one of {FAULTS})")
        with self._lock:
            if fault == "service":
                state = value if value is not None else FAULT_PRESETS["service"]
                if state not in SERVICE_STATES or state == "running":
                    raise ValidationFailed("service fault value must be 'degraded' or 'failed'")
                self._state["service_state"] = state
            else:
                v = FAULT_PRESETS[fault] if value is None else float(value)
                if not 0 <= v <= 100:
                    raise ValidationFailed("fault value must be between 0 and 100")
                self._state[fault] = _clamp(v)
            self._persist()
            return {**self._state, "epoch": self._epoch}

    def set_metric(self, metric: str, value: float, epoch: int | None = None) -> float:
        with self._lock:
            self._check_epoch(epoch)
            self._state[metric] = _clamp(value)
            self._persist()
            return self._state[metric]

    def adjust_metric(self, metric: str, delta: float, epoch: int | None = None) -> float:
        with self._lock:
            self._check_epoch(epoch)
            self._state[metric] = _clamp(self._state[metric] + delta)
            self._persist()
            return self._state[metric]

    def set_service(self, state: str, epoch: int | None = None) -> str:
        if state not in SERVICE_STATES:
            raise ValidationFailed(f"invalid service state '{state}'")
        with self._lock:
            self._check_epoch(epoch)
            self._state["service_state"] = state
            self._persist()
            return state

    def recover_fault(self, fault: str, epoch: int | None = None) -> dict[str, Any]:
        """Return one fault dimension to its baseline (external/spontaneous recovery)."""
        with self._lock:
            self._check_epoch(epoch)
            if fault == "service":
                self._state["service_state"] = BASELINE["service_state"]
            elif fault in NUMERIC:
                self._state[fault] = BASELINE[fault]
            else:
                raise ValidationFailed(f"unknown fault '{fault}'")
            self._persist()
            return {**self._state, "epoch": self._epoch}

    def reset(self) -> dict[str, Any]:
        with self._lock:
            self._state = copy.deepcopy(BASELINE)
            self._epoch += 1
            self._control = {"plans": {}}
            self._persist()
            return {**self._state, "epoch": self._epoch}

    # ------------------------------------------------------------------ scenario control
    def set_plan(self, metric: str, plan: dict[str, Any]) -> None:
        with self._lock:
            self._control["plans"][metric] = plan
            self._persist()

    def pop_plan(self, metric: str) -> dict[str, Any] | None:
        """Consume the scenario plan for a metric (called when its incident is created)."""
        with self._lock:
            plan = self._control["plans"].pop(metric, None)
            if plan is not None:
                self._persist()
            return plan

    def pending_plans(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._control["plans"])
