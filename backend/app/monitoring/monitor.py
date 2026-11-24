"""Singleton monitoring loop: collect -> persist -> evaluate -> detect."""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from ..core.activity import ActivityLog
from ..core.config_service import ConfigService
from ..core.db import Database
from ..core.util import ENV_LABELS, utcnow
from .health import metric_statuses, overall
from .sources import MetricSource, Snapshot

logger = logging.getLogger("autoremed.monitor")


class Monitor:
    def __init__(
        self,
        db: Database,
        config: ConfigService,
        activity: ActivityLog,
        sources: dict[str, MetricSource],
        process_snapshot: Callable[[Snapshot, dict[str, str], dict], Any],
        after_tick: Callable[[], None] | None = None,
        retention: int = 5000,
    ):
        self.db = db
        self.config = config
        self.activity = activity
        self.sources = sources
        self._process = process_snapshot
        self._after_tick = after_tick
        self.retention = retention

        self._thread_lock = threading.Lock()      # guards start/stop -> at most one loop
        self._tick_lock = threading.RLock()       # serializes tick() (loop + manual triggers)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at: str | None = None
        self.tick_count = 0
        self.error_count = 0
        self.last_tick_at: str | None = None
        self.last_error: str | None = None
        self._last_health: dict[str, str] = {}
        self._last_collection_errors: dict[str, tuple[str, ...]] = {}

    # ------------------------------------------------------------------ lifecycle
    def start(self, interval_seconds: float | None = None) -> bool:
        """Start the loop. Returns False (and starts nothing) if it is already running."""
        with self._thread_lock:
            if interval_seconds is not None:
                self.config.set_monitoring(interval_seconds=interval_seconds)
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="autoremed-monitor", daemon=True)
            self._started_at = utcnow()
            self.config.set_monitoring(enabled=True, log=False)
            self._thread.start()
            interval = self.config.monitoring()["interval_seconds"]
        self.activity.log("monitoring_started", f"Monitoring started (interval {interval}s)",
                          action="start_monitoring", status="ok")
        return True

    def stop(self, timeout: float = 10.0) -> bool:
        with self._thread_lock:
            t = self._thread
            if t is None or not t.is_alive():
                self._thread = None
                return False
            self._stop.set()
        t.join(timeout)
        with self._thread_lock:
            self._thread = None
            self._started_at = None
        self.config.set_monitoring(enabled=False, log=False)
        self.activity.log("monitoring_stopped", "Monitoring stopped", action="stop_monitoring", status="ok")
        return True

    def shutdown(self) -> None:
        """Stop the loop without changing the persisted enabled flag (used on app exit)."""
        with self._thread_lock:
            t = self._thread
            self._stop.set()
        if t is not None and t.is_alive():
            t.join(10.0)
        with self._thread_lock:
            self._thread = None

    @property
    def running(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    def status(self) -> dict[str, Any]:
        cfg = self.config.monitoring()
        return {
            "running": self.running,
            "interval_seconds": cfg["interval_seconds"],
            "started_at": self._started_at,
            "tick_count": self.tick_count,
            "error_count": self.error_count,
            "last_tick_at": self.last_tick_at,
            "last_error": self.last_error,
            "thread_count": sum(1 for t in threading.enumerate() if t.name == "autoremed-monitor"),
        }

    # ------------------------------------------------------------------ loop
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # the loop itself must survive anything
                self.error_count += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("monitor tick crashed")
            interval = self.config.monitoring()["interval_seconds"]
            self._stop.wait(interval)

    # ------------------------------------------------------------------ one pass
    def tick(self) -> dict[str, Any]:
        """Collect, persist and evaluate both environments once. Safe to call from any thread."""
        with self._tick_lock:
            thresholds = self.config.thresholds()
            result: dict[str, Any] = {}
            for env, source in self.sources.items():
                try:
                    snap = source.collect()
                    statuses = metric_statuses(snap.to_dict(), thresholds)
                    health = overall(statuses)
                    self._persist(snap, health)
                    self._note(env, snap, health)
                    self._process(snap, statuses, thresholds)
                    result[env] = {"health": health, "statuses": statuses, **snap.to_dict()}
                except Exception as exc:
                    self.error_count += 1
                    self.last_error = f"{env}: {type(exc).__name__}: {exc}"
                    logger.exception("monitoring failure for %s", env)
                    try:
                        self.activity.log("monitor_error", f"Monitoring error in {ENV_LABELS[env]}: {exc}",
                                          action="tick", status="error", environment=env)
                    except Exception:
                        logger.exception("could not record monitor error")
            if self._after_tick is not None:
                try:
                    self._after_tick()
                except Exception:
                    logger.exception("after-tick hook failed")
            self.tick_count += 1
            self.last_tick_at = utcnow()
            if self.tick_count % 50 == 0:
                self._prune()
            return result

    def _persist(self, snap: Snapshot, health: str) -> None:
        self.db.execute(
            "INSERT INTO metrics (ts, environment, cpu, memory, disk, service_state, health)"
            " VALUES (?,?,?,?,?,?,?)",
            (snap.ts, snap.environment, snap.cpu, snap.memory, snap.disk, snap.service_state, health),
        )

    def _note(self, env: str, snap: Snapshot, health: str) -> None:
        """Log first collection, health transitions and collection errors (not every sample)."""
        errs = tuple(snap.errors)
        if errs and self._last_collection_errors.get(env) != errs:
            self.activity.log("metric_collection_error",
                              f"{ENV_LABELS[env]} metric(s) unavailable: {'; '.join(errs)}",
                              action="collect_metrics", status="error", environment=env,
                              details={"errors": list(errs)})
        self._last_collection_errors[env] = errs
        prev = self._last_health.get(env)
        if prev != health:
            msg = (f"{ENV_LABELS[env]} metric collection active, health={health}" if prev is None
                   else f"{ENV_LABELS[env]} health changed: {prev} -> {health}")
            self.activity.log("metric_collection" if prev is None else "health_changed", msg,
                              action="collect_metrics", status=health, environment=env,
                              details={"cpu": snap.cpu, "memory": snap.memory, "disk": snap.disk,
                                       "service_state": snap.service_state})
            self._last_health[env] = health

    def _prune(self) -> None:
        for env in self.sources:
            self.db.execute(
                "DELETE FROM metrics WHERE environment = ? AND id NOT IN"
                " (SELECT id FROM metrics WHERE environment = ? ORDER BY id DESC LIMIT ?)",
                (env, env, self.retention),
            )

    # ------------------------------------------------------------------ reads
    def current(self) -> dict[str, Any]:
        """Live read of both sources (not persisted, no detection)."""
        thresholds = self.config.thresholds()
        out: dict[str, Any] = {}
        for env, source in self.sources.items():
            snap = source.collect()
            statuses = metric_statuses(snap.to_dict(), thresholds)
            out[env] = {"health": overall(statuses), "statuses": statuses, **snap.to_dict()}
        return out

    def history(self, environment: str, limit: int = 120) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT ts, environment, cpu, memory, disk, service_state, health FROM metrics"
            " WHERE environment = ? ORDER BY id DESC LIMIT ?", (environment, limit))
        rows.reverse()
        return rows
