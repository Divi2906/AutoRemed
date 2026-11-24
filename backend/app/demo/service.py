"""Demo Center: controlled, repeatable faults that flow through the REAL detection/remediation pipeline.

A scenario only (a) sets simulated state, (b) stores a per-metric *plan* that controls the simulated
executor's outcome for each attempt, and (c) runs one normal monitoring pass. Detection, diagnosis,
strategy selection, execution, verification, retry and escalation are the production code paths.
"""
from __future__ import annotations

from typing import Any

from ..core.activity import ActivityLog
from ..core.db import Database
from ..core.errors import Conflict, NotFound, ValidationFailed
from ..core.util import ENV_SIM, dumps, new_id, utcnow
from ..incidents.diagnosis import TYPE_BY_METRIC
from ..incidents.engine import fingerprint
from ..incidents.repository import Repositories
from ..monitoring.monitor import Monitor
from ..remediation.orchestrator import RemediationOrchestrator
from ..simulation.state import FAULTS, SimulationState

# plan outcomes per attempt: recover | exec_fail | partial (exec ok, still unhealthy) | no_effect
SCENARIOS: dict[str, dict[str, Any]] = {
    "first_attempt_succeeds": {
        "title": "First attempt succeeds", "group": "remediation",
        "description": "Attempt 1 executes and the verifier confirms recovery. Exactly 1 attempt.",
        "plan": ["recover"], "mode": None, "expected": "Resolved after 1 attempt"},
    "second_attempt_succeeds": {
        "title": "Attempt 1 fails, attempt 2 succeeds", "group": "retry",
        "description": "Attempt 1's execution fails; a different strategy is chosen and succeeds.",
        "plan": ["exec_fail", "recover"], "mode": None, "expected": "Resolved after 2 attempts"},
    "third_attempt_succeeds": {
        "title": "Attempts 1 & 2 fail, attempt 3 succeeds", "group": "retry",
        "description": "Two failed attempts (one execution failure, one that leaves the issue unresolved), "
                       "then success on the final allowed attempt.",
        "plan": ["exec_fail", "partial", "recover"], "mode": None, "expected": "Resolved after 3 attempts"},
    "all_attempts_fail": {
        "title": "All 3 attempts fail -> escalation", "group": "escalation",
        "description": "Every attempt fails (execution failure, partial improvement, execution failure). "
                       "Automation stops after exactly 3 attempts and escalates for manual intervention.",
        "plan": ["exec_fail", "partial", "exec_fail"], "mode": None,
        "expected": "Escalated after exactly 3 attempts, manual intervention required"},
    "verification_fails": {
        "title": "Execution succeeds but verification fails", "group": "retry",
        "description": "Attempt 1 reports success but the independent verifier finds the issue remains, "
                       "so a retry is initiated and attempt 2 recovers.",
        "plan": ["partial", "recover"], "mode": None, "expected": "Retry after failed verification; resolved after 2 attempts"},
    "recovers_before_remediation": {
        "title": "Incident recovers before remediation", "group": "recovery",
        "description": "The fault clears on its own after detection but before remediation begins. "
                       "Pre-flight health check finds it healthy: zero executions.",
        "plan": [], "pre_flight": "self_recover", "mode": None, "expected": "Resolved with 0 executions"},
    "approval_required": {
        "title": "Approval required", "group": "approval",
        "description": "Approval Mode for this incident: a diagnosis and proposed strategy are generated and "
                       "nothing executes until you approve or reject it in the Remediation Center.",
        "plan": ["recover"], "mode": "approval", "expected": "Pending approval; executes only after approval"},
    "action_rejected": {
        "title": "Action rejected", "group": "approval",
        "description": "Approval Mode: the proposed remediation is rejected automatically. "
                       "The rejected action must never execute.",
        "plan": ["recover"], "mode": "approval", "auto_reject": True,
        "expected": "Rejected; zero executions; manual intervention flagged"},
}


class DemoService:
    def __init__(self, db: Database, repos: Repositories, activity: ActivityLog, sim: SimulationState,
                 monitor: Monitor, orchestrator: RemediationOrchestrator):
        self.db, self.repos, self.activity, self.sim = db, repos, activity, sim
        self.monitor, self.orchestrator = monitor, orchestrator

    def scenarios(self) -> dict[str, Any]:
        return {
            "faults": [
                {"id": "cpu", "label": "High CPU", "initial": "96% CPU"},
                {"id": "memory", "label": "High memory", "initial": "94% memory"},
                {"id": "disk", "label": "Critical disk usage", "initial": "97% disk"},
                {"id": "service", "label": "Service failure", "initial": "service 'failed'"},
            ],
            "scenarios": [{"id": k, **{kk: vv for kk, vv in v.items() if kk in
                                       ("title", "group", "description", "plan", "mode", "expected")}}
                          for k, v in SCENARIOS.items()],
        }

    # ------------------------------------------------------------------ fault injection
    def inject(self, fault: str, *, value: float | str | None = None, plan: list[str] | None = None,
               mode_override: str | None = None, scenario: str | None = None, pre_flight: str | None = None,
               source: str = "api") -> dict[str, Any]:
        if fault not in FAULTS:
            raise ValidationFailed(f"unknown fault '{fault}' (expected one of {list(FAULTS)})")
        fp = fingerprint(ENV_SIM, TYPE_BY_METRIC[fault], fault)
        active = self.repos.active_incident_by_fingerprint(fp)
        if active is not None:
            raise Conflict(
                f"an active incident ({active['id']}, status {active['status']}) already exists for this fault; "
                "wait for it to finish or reset the demo", details={"incident_id": active["id"]})
        if mode_override not in (None, "autonomous", "approval"):
            raise ValidationFailed("mode_override must be 'autonomous' or 'approval'")
        self.sim.set_plan(fault, {"plan": plan or [], "mode_override": mode_override, "scenario": scenario,
                                  "pre_flight": pre_flight})
        before = self.sim.snapshot()
        state = self.sim.inject_fault(fault, value)
        self.activity.log("demo_trigger", f"Fault injected into SIMULATION: {fault}"
                          + (f" (scenario: {scenario})" if scenario else ""),
                          action="inject_fault", status="ok", environment=ENV_SIM,
                          details={"fault": fault, "scenario": scenario, "plan": plan, "before": before,
                                   "after": state, "source": source})
        # Feed the real pipeline: one normal monitoring pass (repeated if consecutive violations are required).
        incident = None
        for _ in range(self.monitor.config.consecutive_required(ENV_SIM)):
            self.monitor.tick()
            incident = self.repos.active_incident_by_fingerprint(fp) or self._latest_for(fp)
            if incident:
                break
        return {"fault": fault, "scenario": scenario, "state": state, "incident_id": incident["id"] if incident else None}

    def _latest_for(self, fp: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT id FROM incidents WHERE fingerprint=? ORDER BY created_at DESC LIMIT 1", (fp,))
        return self.repos.incident(row["id"]) if row else None

    def trigger(self, scenario: str, fault: str) -> dict[str, Any]:
        sc = SCENARIOS.get(scenario)
        if sc is None:
            raise NotFound(f"unknown scenario '{scenario}'")
        run_id, now = new_id("DEMO"), utcnow()
        res = self.inject(fault, plan=list(sc["plan"]), mode_override=sc["mode"], scenario=scenario,
                          pre_flight=sc.get("pre_flight"), source="demo")
        incident_id = res["incident_id"]
        note = None
        if sc.get("auto_reject") and incident_id:
            rem = self.repos.remediation_for_incident(incident_id)
            if rem and rem["approval_state"] == "pending":
                self.orchestrator.reject(rem["id"], actor="demo-scenario", note="auto-rejected by demo scenario")
                note = "proposal auto-rejected by scenario"
        self.db.execute(
            "INSERT INTO demo_runs (id, ts, scenario, fault, incident_id, status, params_json, note)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (run_id, now, scenario, fault, incident_id, "triggered", dumps({"plan": sc["plan"], "mode": sc["mode"]}), note))
        return {"run_id": run_id, "scenario": scenario, "fault": fault, "incident_id": incident_id,
                "expected": sc["expected"], "note": note}

    def recover(self, fault: str) -> dict[str, Any]:
        """Simulate an external recovery of one fault (e.g. an operator fixing it) and run a monitoring pass."""
        if fault not in FAULTS:
            raise ValidationFailed(f"unknown fault '{fault}'")
        state = self.sim.recover_fault(fault)
        self.activity.log("demo_recover", f"Simulated external recovery of '{fault}'", action="recover_fault",
                          status="ok", environment=ENV_SIM, details={"state": state})
        self.monitor.tick()
        return {"fault": fault, "state": state}

    def reset(self) -> dict[str, Any]:
        """Reset the simulation. Active simulation incidents are closed; ALL history is retained."""
        state = self.sim.reset()   # epoch bump: in-flight actions cannot write into the clean state
        now = utcnow()
        closed = 0
        with self.db.tx() as c:
            rows = c.execute("SELECT id, status FROM incidents WHERE is_active=1 AND environment='simulation'").fetchall()
            for r in rows:
                if r["status"] in ("escalated", "rejected"):
                    c.execute("UPDATE incidents SET is_active=0, closed_reason='demo_reset', updated_at=? WHERE id=?",
                              (now, r["id"]))
                else:
                    c.execute(
                        "UPDATE incidents SET status='cancelled', is_active=0, workflow_state='finished',"
                        " closed_reason='demo_reset', resolution='Cancelled by demo reset', updated_at=? WHERE id=?",
                        (now, r["id"]))
                    c.execute("UPDATE remediations SET status='cancelled', approval_state=CASE WHEN"
                              " approval_state='pending' THEN 'cancelled' ELSE approval_state END, updated_at=?,"
                              " completed_at=? WHERE incident_id=? AND status IN"
                              " ('pending_approval','approved','in_progress')", (now, now, r["id"]))
                closed += 1
            self.activity.log("demo_reset", f"Simulation reset to baseline; {closed} active simulation incident(s) "
                              "closed (history retained)", action="reset", status="ok", environment=ENV_SIM,
                              details={"closed_incidents": closed, "state": state})
        self.monitor.tick()
        return {"state": state, "closed_incidents": closed}

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        runs = self.repos.demo_runs(limit)
        for r in runs:
            inc = self.repos.incident(r["incident_id"]) if r.get("incident_id") else None
            r["incident_status"] = inc["status"] if inc else None
            r["attempts_made"] = inc["attempts_made"] if inc else None
        return runs
