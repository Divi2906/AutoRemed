"""Incident detection and lifecycle management.

Responsibilities: threshold-violation tracking (consecutive samples), incident creation with a
fingerprint (duplicates are prevented in-code AND by a partial unique index), severity upgrades,
diagnosis at creation, and recovery detection for incidents that no remediation workflow owns.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from typing import Any, Callable

from ..core.activity import ActivityLog
from ..core.config_service import ConfigService
from ..core.db import Database
from ..core.util import ENV_LABELS, ENV_REAL, ENV_SIM, dumps, new_id, utcnow
from ..monitoring.sources import Snapshot
from ..simulation.state import SimulationState
from .diagnosis import TYPE_BY_METRIC, DiagnosisEngine
from .repository import Repositories

logger = logging.getLogger("autoremed.incidents")


def fingerprint(environment: str, incident_type: str, metric: str) -> str:
    return f"{environment}:{incident_type}:{metric}"


def _fmt(metric: str, value: Any) -> str:
    return str(value) if metric == "service" else f"{float(value):.1f}%"


class IncidentEngine:
    def __init__(
        self,
        db: Database,
        repos: Repositories,
        config: ConfigService,
        activity: ActivityLog,
        diagnosis: DiagnosisEngine,
        sim: SimulationState,
    ):
        self.db, self.repos, self.config, self.activity = db, repos, config, activity
        self.diagnosis_engine, self.sim = diagnosis, sim
        self.on_created: Callable[[str], None] | None = None   # wired to the orchestrator
        self._counters: dict[str, int] = {}
        self._lock = threading.RLock()

    # ================================================================== detection
    def process_snapshot(self, snap: Snapshot, statuses: dict[str, str], thresholds: dict[str, dict[str, float]]) -> None:
        env = snap.environment
        required = self.config.consecutive_required(env)
        data = snap.to_dict()
        metrics = [m for m in ("cpu", "memory", "disk") if data.get(m) is not None]
        if data.get("service_state") is not None:
            metrics.append("service")
        for metric in metrics:
            status = statuses.get(metric, "unknown")
            itype = TYPE_BY_METRIC[metric]
            fp = fingerprint(env, itype, metric)
            value = data["service_state"] if metric == "service" else data[metric]
            if status in ("warning", "critical"):
                with self._lock:
                    self._counters[fp] = self._counters.get(fp, 0) + 1
                    count = self._counters[fp]
                if count >= required:
                    self._on_violation(env, itype, metric, status, value, thresholds, data, statuses)
            elif status == "ok":
                with self._lock:
                    self._counters[fp] = 0
                self._on_healthy(fp, env, metric, value)

    # ------------------------------------------------------------------ violation
    def _on_violation(self, env, itype, metric, severity, value, thresholds, snapshot, statuses) -> None:
        fp = fingerprint(env, itype, metric)
        existing = self.repos.active_incident_by_fingerprint(fp)
        if existing is not None:
            if severity == "critical" and existing["severity"] == "warning":
                self._upgrade_severity(existing, value, thresholds, metric)
            return  # same active condition: never a duplicate incident
        self.create_incident(env, itype, metric, severity, value, thresholds, snapshot, statuses)

    def create_incident(self, env, itype, metric, severity, value, thresholds, snapshot, statuses) -> str | None:
        fp = fingerprint(env, itype, metric)
        if metric == "service":
            thr, thr_label, val_num = None, "running", None
            value_label = str(value)
        else:
            thr = thresholds[metric]["critical" if severity == "critical" else "warning"]
            thr_label, val_num, value_label = f"{thr:.1f}%", float(value), _fmt(metric, value)
        diag = self.diagnosis_engine.diagnose(
            incident_type=itype, severity=severity, environment=env, metric=metric, value_label=value_label,
            threshold_label=thr_label, snapshot=snapshot, statuses=statuses, thresholds=thresholds)
        plan = self.sim.pop_plan(metric) if env == ENV_SIM else None
        mode = (plan or {}).get("mode_override") or self.config.mode()
        observe_only = env != ENV_SIM
        incident_id = new_id("INC")
        now = utcnow()
        env_label = ENV_LABELS[env]
        description = (f"{diag.summary}" if metric != "service"
                       else f"Service state '{value}' in {env_label} (expected 'running').")
        try:
            with self.db.tx() as c:
                c.execute(
                    "INSERT INTO incidents (id, fingerprint, type, severity, environment, metric, value, threshold,"
                    " value_label, threshold_label, description, root_cause, status, is_active, workflow_state,"
                    " mode, observe_only, diagnosis_json, scenario_json, recommended_action, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'detected',1,'idle',?,?,?,?,?,?,?)",
                    (incident_id, fp, itype, severity, env, metric, val_num, thr, value_label, thr_label,
                     description, diag.probable_root_cause, mode, int(observe_only), dumps(diag.to_dict()),
                     dumps(plan) if plan else None, diag.recommended_manual_step, now, now))
                self.activity.log(
                    "incident_detected", f"{severity.upper()} incident detected: {description}",
                    incident_id=incident_id, action="detect", status="detected", environment=env,
                    details={"fingerprint": fp, "value": value, "threshold": thr_label, "mode": mode,
                             "scenario": (plan or {}).get("scenario")})
                self.repos.transition(c, incident_id, "investigating")
                self.activity.log(
                    "diagnosis", f"Diagnosis [{diag.rule_id}]: {diag.probable_root_cause}",
                    incident_id=incident_id, action="diagnose", status="investigating", environment=env,
                    details=diag.to_dict())
        except sqlite3.IntegrityError:
            # Another thread created the same active incident first: DB-level duplicate guard.
            logger.info("duplicate incident prevented by unique index: %s", fp)
            return None
        if self.on_created is not None:
            try:
                self.on_created(incident_id)
            except Exception:
                logger.exception("on_created handler failed for %s", incident_id)
                self.activity.log("workflow_error", "Failed to start remediation workflow",
                                  incident_id=incident_id, action="dispatch", status="error", environment=env)
        return incident_id

    def _upgrade_severity(self, existing: dict[str, Any], value: Any, thresholds, metric: str) -> None:
        thr = None if metric == "service" else thresholds[metric]["critical"]
        with self.db.tx() as c:
            cur = c.execute("SELECT severity FROM incidents WHERE id=? AND is_active=1", (existing["id"],)).fetchone()
            if cur is None or cur["severity"] != "warning":
                return
            c.execute(
                "UPDATE incidents SET severity='critical', threshold=?, threshold_label=?, value=?, value_label=?,"
                " updated_at=? WHERE id=?",
                (thr, "running" if thr is None else f"{thr:.1f}%", None if metric == "service" else float(value),
                 _fmt(metric, value), utcnow(), existing["id"]))
            self.activity.log("severity_upgraded", f"Severity upgraded warning -> critical ({_fmt(metric, value)})",
                              incident_id=existing["id"], action="upgrade_severity", status="critical",
                              environment=existing["environment"])

    # ------------------------------------------------------------------ recovery detection
    def _on_healthy(self, fp: str, env: str, metric: str, value: Any) -> None:
        inc = self.repos.active_incident_by_fingerprint(fp)
        if inc is None:
            return
        self.close_if_recovered(inc["id"], value_label=_fmt(metric, value))

    def close_if_recovered(self, incident_id: str, value_label: str = "") -> bool:
        """The condition is healthy again. Close the incident unless a workflow currently owns it."""
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM incidents WHERE id=? AND is_active=1", (incident_id,)).fetchone()
            if row is None or row["workflow_state"] == "running":
                return False  # the remediation workflow owns it and will verify on its own
            now, status = utcnow(), row["status"]
            if status in ("escalated", "rejected"):
                c.execute("UPDATE incidents SET is_active=0, closed_reason=?, updated_at=? WHERE id=?",
                          (f"recovered_after_{status}", now, incident_id))
                msg = f"Condition recovered after the incident was {status}; incident closed ({value_label})"
            elif status in ("detected", "investigating", "pending_approval", "approved"):
                kind = "recovered_before_remediation" if row["attempts_made"] == 0 else "recovered"
                self.repos.transition(
                    c, incident_id, "resolved", is_active=0, resolved_at=now, resolution_type=kind,
                    workflow_state="finished",
                    resolution="Condition recovered on its own before any remediation was executed "
                               "(no unnecessary action taken)." if kind == "recovered_before_remediation"
                    else "Condition recovered between attempts.")
                c.execute("UPDATE remediations SET status='cancelled', approval_state="
                          "CASE WHEN approval_state='pending' THEN 'cancelled' ELSE approval_state END,"
                          " updated_at=?, completed_at=? WHERE incident_id=? AND status IN"
                          " ('pending_approval','approved','in_progress')", (now, now, incident_id))
                msg = f"Condition recovered before remediation ({value_label}); incident resolved with no action"
            else:
                return False
            self.activity.log("incident_recovered", msg, incident_id=incident_id, action="detect_recovery",
                              status="resolved", environment=row["environment"])
            return True
