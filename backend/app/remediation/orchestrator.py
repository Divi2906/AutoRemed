"""Remediation workflow orchestration: diagnose -> select -> execute -> verify -> retry -> resolve/escalate.

Reliability guarantees (all enforced in the database, not just in memory):

* One workflow per incident: ``_claim`` atomically flips ``workflow_state`` idle/awaiting_approval ->
  running; a second claim gets rowcount 0. ``remediations.incident_id`` is UNIQUE as well.
* Attempt limit: ``_reserve_attempt`` is a compare-and-set on ``attempts_made`` (must equal attempt-1
  and be < MAX_ATTEMPTS) in the same transaction that inserts the execution row; the executions
  table additionally has UNIQUE(incident_id, attempt) and CHECK(attempt BETWEEN 1 AND 3).
* Attempt counts are persisted, so a restart resumes at the right attempt, never from zero.
* Executors only ever receive simulation incidents; anything else is refused.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from ..core.activity import ActivityLog
from ..core.config_service import ConfigService
from ..core.db import Database
from ..core.errors import AttemptLimitReached, Conflict, NotFound, SafetyViolation
from ..core.util import ENV_SIM, dumps, duration_ms, new_id, utcnow
from ..incidents.engine import IncidentEngine
from ..incidents.repository import TERMINAL, Repositories
from ..settings import MAX_ATTEMPTS, Settings
from ..simulation.state import SimulationState
from .executors import ExecutionRequest, ExecutionResult, ExecutorRegistry
from .strategies import AttemptRecord, SelectionContext, StrategyDecision, StrategySelector
from .verifier import HealthVerifier

logger = logging.getLogger("autoremed.orchestrator")

_FAULT_BY_METRIC = {"cpu": "cpu", "memory": "memory", "disk": "disk", "service": "service"}


class RemediationOrchestrator:
    def __init__(
        self,
        db: Database,
        repos: Repositories,
        config: ConfigService,
        activity: ActivityLog,
        engine: IncidentEngine,
        selector: StrategySelector,
        executors: ExecutorRegistry,
        verifier: HealthVerifier,
        sim: SimulationState,
        settings: Settings,
    ):
        self.db, self.repos, self.config, self.activity = db, repos, config, activity
        self.engine, self.selector, self.executors, self.verifier, self.sim = engine, selector, executors, verifier, sim
        self.settings = settings
        self._stop = threading.Event()
        self._pool: ThreadPoolExecutor | None = None
        if not settings.sync_dispatch:
            self._pool = ThreadPoolExecutor(max_workers=settings.worker_threads, thread_name_prefix="remediation")
        self._futures: set[Future] = set()
        self._futures_lock = threading.Lock()

    # ================================================================== entry points
    def handle_new_incident(self, incident_id: str) -> None:
        inc = self.repos.require_incident(incident_id)
        if inc["observe_only"] or inc["environment"] != ENV_SIM:
            self.activity.log("observe_only", "Real-host incident recorded for visibility only; "
                              "AutoRemed never remediates the real host.",
                              incident_id=incident_id, action="observe", status="observe_only",
                              environment=inc["environment"])
            return
        if inc["mode"] == "approval":
            self.propose(incident_id)
        else:
            self.dispatch(incident_id)

    def dispatch(self, incident_id: str) -> None:
        if self._pool is None:
            self._safe_run(incident_id)
            return
        if self._stop.is_set():
            return
        fut = self._pool.submit(self._safe_run, incident_id)
        with self._futures_lock:
            self._futures.add(fut)
        fut.add_done_callback(lambda f: self._futures.discard(f))

    def _safe_run(self, incident_id: str) -> None:
        try:
            self.run_workflow(incident_id)
        except Exception:
            logger.exception("remediation workflow crashed for %s", incident_id)

    def dispatch_pending(self) -> int:
        """Safety net / restart recovery: (re)start workflows that should be running but are not."""
        rows = self.db.query(
            "SELECT id FROM incidents WHERE is_active = 1 AND observe_only = 0 AND environment = 'simulation'"
            " AND workflow_state IN ('idle','awaiting_approval')"
            " AND status IN ('detected','investigating','approved','remediating','retry_in_progress')"
            " AND (mode = 'autonomous' OR id IN (SELECT incident_id FROM remediations WHERE approval_state='approved'))")
        for r in rows:
            self.dispatch(r["id"])
        return len(rows)

    def resume_after_restart(self) -> int:
        """Called once at startup: release workflows orphaned by a crash, then resume them."""
        orphans = self.db.query("SELECT id, attempts_made FROM incidents WHERE workflow_state = 'running'")
        for o in orphans:
            with self.db.tx() as c:
                c.execute("UPDATE executions SET status='failed', ended_at=?, error=?, message=? "
                          "WHERE incident_id=? AND status='running'",
                          (utcnow(), "interrupted by backend restart", "execution interrupted", o["id"]))
                c.execute("UPDATE incidents SET workflow_state='idle', updated_at=? WHERE id=?", (utcnow(), o["id"]))
                self.activity.log("workflow_resumed",
                                  f"Workflow orphaned by restart; resuming from attempt {o['attempts_made'] + 1} "
                                  f"(attempt count preserved)", incident_id=o["id"], action="resume", status="idle")
        return self.dispatch_pending()

    def shutdown(self) -> None:
        self._stop.set()
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Block until no workflow futures remain (used by tests/tools)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._futures_lock:
                if not self._futures:
                    return True
            time.sleep(0.02)
        return False

    # ================================================================== approval workflow
    def propose(self, incident_id: str) -> str | None:
        inc = self.repos.require_incident(incident_id)
        decision = self._make_decision(inc, 1, [])
        rid = new_id("REM")
        now = utcnow()
        with self.db.tx() as c:
            cur = c.execute("SELECT status, is_active FROM incidents WHERE id=?", (incident_id,)).fetchone()
            if not cur["is_active"] or cur["status"] not in ("detected", "investigating"):
                return None
            if c.execute("SELECT 1 FROM remediations WHERE incident_id=?", (incident_id,)).fetchone():
                return None
            c.execute(
                "INSERT INTO remediations (id, incident_id, mode, approval_state, status, proposed_strategy,"
                " proposal_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (rid, incident_id, "approval", "pending", "pending_approval", decision.strategy.name,
                 dumps(self._decision_dict(decision)), now, now))
            self._save_decision(c, inc, rid, decision)
            c.execute("UPDATE incidents SET workflow_state='awaiting_approval' WHERE id=?", (incident_id,))
            self.repos.transition(c, incident_id, "pending_approval")
            c.execute("INSERT INTO approvals (id, remediation_id, incident_id, action, actor, note, created_at)"
                      " VALUES (?,?,?,?,?,?,?)", (new_id("APR"), rid, incident_id, "requested", "system",
                                                  decision.reason, now))
            self.activity.log("approval_requested",
                              f"Approval requested for `{decision.strategy.name}`: {decision.reason}",
                              incident_id=incident_id, action="request_approval", status="pending_approval",
                              environment=inc["environment"], details={"remediation_id": rid})
        return rid

    def approve(self, remediation_id: str, actor: str = "operator", note: str | None = None) -> dict[str, Any]:
        rem = self.repos.remediation(remediation_id)
        if rem is None:
            raise NotFound(f"remediation '{remediation_id}' not found")
        now = utcnow()
        with self.db.tx() as c:
            cur = c.execute("UPDATE remediations SET approval_state='approved', status='approved', updated_at=?"
                            " WHERE id=? AND approval_state='pending'", (now, remediation_id))
            if cur.rowcount != 1:
                state = c.execute("SELECT approval_state FROM remediations WHERE id=?", (remediation_id,)).fetchone()
                raise Conflict(f"remediation is not pending approval (state: {state['approval_state']})")
            inc = c.execute("SELECT status, is_active, environment FROM incidents WHERE id=?",
                            (rem["incident_id"],)).fetchone()
            if not inc["is_active"] or inc["status"] != "pending_approval":
                raise Conflict(f"incident is no longer awaiting approval (status: {inc['status']})")
            self.repos.transition(c, rem["incident_id"], "approved")
            c.execute("INSERT INTO approvals (id, remediation_id, incident_id, action, actor, note, created_at)"
                      " VALUES (?,?,?,?,?,?,?)", (new_id("APR"), remediation_id, rem["incident_id"], "approved",
                                                  actor, note, now))
            self.activity.log("approval_approved", f"Remediation approved by {actor}",
                              incident_id=rem["incident_id"], action="approve", status="approved",
                              environment=inc["environment"], details={"remediation_id": remediation_id, "note": note})
        self.dispatch(rem["incident_id"])
        return self.repos.remediation(remediation_id)

    def reject(self, remediation_id: str, actor: str = "operator", note: str | None = None) -> dict[str, Any]:
        rem = self.repos.remediation(remediation_id)
        if rem is None:
            raise NotFound(f"remediation '{remediation_id}' not found")
        now = utcnow()
        with self.db.tx() as c:
            cur = c.execute("UPDATE remediations SET approval_state='rejected', status='rejected', updated_at=?,"
                            " completed_at=? WHERE id=? AND approval_state='pending'", (now, now, remediation_id))
            if cur.rowcount != 1:
                state = c.execute("SELECT approval_state FROM remediations WHERE id=?", (remediation_id,)).fetchone()
                raise Conflict(f"remediation is not pending approval (state: {state['approval_state']})")
            inc = c.execute("SELECT environment FROM incidents WHERE id=?", (rem["incident_id"],)).fetchone()
            self.repos.transition(
                c, rem["incident_id"], "rejected", workflow_state="finished", manual_intervention_required=1,
                resolution="Automated remediation was rejected by the operator; no action was executed. "
                           "Manual intervention required.", resolution_type="rejected")
            c.execute("INSERT INTO approvals (id, remediation_id, incident_id, action, actor, note, created_at)"
                      " VALUES (?,?,?,?,?,?,?)", (new_id("APR"), remediation_id, rem["incident_id"], "rejected",
                                                  actor, note, now))
            self.activity.log("approval_rejected", f"Remediation rejected by {actor}; nothing will be executed",
                              incident_id=rem["incident_id"], action="reject", status="rejected",
                              environment=inc["environment"], details={"remediation_id": remediation_id, "note": note})
        return self.repos.remediation(remediation_id)

    # ================================================================== workflow
    def _claim(self, incident_id: str) -> str | None:
        """Atomically take ownership of an incident's workflow. Returns the remediation id or None."""
        with self.db.tx() as c:
            inc = c.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
            if inc is None or not inc["is_active"] or inc["status"] in TERMINAL:
                return None
            if inc["observe_only"] or inc["environment"] != ENV_SIM:
                return None
            rem = c.execute("SELECT * FROM remediations WHERE incident_id=?", (incident_id,)).fetchone()
            if inc["mode"] == "approval" and (rem is None or rem["approval_state"] != "approved"):
                return None  # unapproved (pending/rejected/cancelled) remediation can never execute
            if rem is not None and rem["status"] in ("rejected", "cancelled", "resolved", "escalated"):
                return None
            cur = c.execute("UPDATE incidents SET workflow_state='running', updated_at=? WHERE id=? AND is_active=1"
                            " AND workflow_state IN ('idle','awaiting_approval')", (utcnow(), incident_id))
            if cur.rowcount != 1:
                return None
            now = utcnow()
            if rem is None:
                rid = new_id("REM")
                c.execute("INSERT INTO remediations (id, incident_id, mode, approval_state, status, created_at,"
                          " updated_at) VALUES (?,?,?,?,?,?,?)",
                          (rid, incident_id, inc["mode"], "not_required", "in_progress", now, now))
            else:
                rid = rem["id"]
                c.execute("UPDATE remediations SET status='in_progress', updated_at=? WHERE id=?", (now, rid))
            return rid

    def run_workflow(self, incident_id: str) -> dict[str, Any] | None:
        rid = self._claim(incident_id)
        if rid is None:
            return None
        try:
            inc = self.repos.require_incident(incident_id)
            self.activity.log("workflow_started", f"Remediation workflow started (mode: {inc['mode']}, "
                              f"attempts already made: {inc['attempts_made']}/{MAX_ATTEMPTS})",
                              incident_id=incident_id, action="workflow", status="started",
                              environment=inc["environment"])
            self._loop(incident_id, rid)
        except Exception as exc:
            logger.exception("workflow error for %s", incident_id)
            self.activity.log("workflow_error", f"Workflow failed unexpectedly: {type(exc).__name__}: {exc}",
                              incident_id=incident_id, action="workflow", status="error")
            self._escalate(incident_id, rid, f"internal workflow error: {type(exc).__name__}: {exc}")
        finally:
            self.db.execute("UPDATE incidents SET workflow_state='idle' WHERE id=? AND workflow_state='running'",
                            (incident_id,))
        return self.repos.incident(incident_id)

    def _loop(self, incident_id: str, rid: str) -> None:
        first = True
        while not self._stop.is_set():
            inc = self.repos.require_incident(incident_id)
            if not inc["is_active"] or inc["status"] in TERMINAL:
                return
            if first:
                first = False
                if inc["attempts_made"] == 0:
                    self._scenario_pre_flight(inc)
            # Pre-flight: never act on a condition that has already cleared.
            if self.verifier.is_healthy(inc):
                before_any = inc["attempts_made"] == 0
                self._resolve(
                    incident_id, rid,
                    resolution_type="recovered_before_remediation" if before_any else "recovered",
                    resolution=("Condition recovered before remediation started; no action was executed."
                                if before_any else "Condition recovered between attempts (verified healthy)."))
                return
            attempt = inc["attempts_made"] + 1
            if attempt > MAX_ATTEMPTS:
                self._escalate(incident_id, rid, f"retry limit of {MAX_ATTEMPTS} attempts reached")
                return
            history = self._history(incident_id)
            decision = self._decision_from_row(self.repos.decision(incident_id, attempt))
            if decision is None:
                decision = self._make_decision(inc, attempt, history)
                with self.db.tx() as c:
                    self._save_decision(c, inc, rid, decision, log=True)
            if self._sleep():
                return
            try:
                exec_id = self._reserve_attempt(inc, rid, decision, attempt)
            except AttemptLimitReached as exc:
                self.activity.log("attempt_refused", str(exc), incident_id=incident_id, action="reserve_attempt",
                                  status="refused", attempt=attempt)
                return
            before = self.verifier.capture()
            result = self._execute(inc, decision, attempt, exec_id)
            if self._sleep():
                return
            ver = self.verifier.verify(inc, attempt, exec_id, before)
            if ver["recovered"]:
                note = ("" if result.status == "success"
                        else " (the executor reported a failure but the independent check found the state healthy)")
                self._resolve(
                    incident_id, rid, resolution_type="remediated",
                    resolution=f"Resolved after {attempt} attempt(s) using `{decision.strategy.name}`; recovery was "
                               f"independently verified{note}.")
                return
            if attempt >= MAX_ATTEMPTS:
                self._escalate(incident_id, rid, f"all {MAX_ATTEMPTS} attempts failed; last failure: "
                                                 f"{ver['failure_reason']}")
                return
            if result.status == "failed":
                kind, detail = "execution failed", result.error or result.message
            else:
                kind, detail = "execution succeeded but the issue remains", ver["failure_reason"]
            with self.db.tx() as c:
                self.repos.transition(c, incident_id, "retry_in_progress")
                self.activity.log(
                    "retry_scheduled",
                    f"Attempt {attempt} did not resolve the incident ({kind}: {detail}); retrying "
                    f"with an adjusted strategy ({attempt + 1}/{MAX_ATTEMPTS})",
                    incident_id=incident_id, action="retry", status="retry_in_progress", attempt=attempt,
                    environment=inc["environment"])

    # ------------------------------------------------------------------ attempt mechanics
    def _reserve_attempt(self, inc: dict[str, Any], rid: str, decision: StrategyDecision, attempt: int) -> str:
        exec_id, now = new_id("EXE"), utcnow()
        status = "remediating" if attempt == 1 else "retry_in_progress"
        with self.db.tx() as c:
            cur = c.execute(
                "UPDATE incidents SET attempts_made = attempts_made + 1, updated_at = ? WHERE id = ? AND is_active = 1"
                " AND workflow_state = 'running' AND attempts_made = ? AND attempts_made < ?",
                (now, inc["id"], attempt - 1, MAX_ATTEMPTS))
            if cur.rowcount != 1:
                raise AttemptLimitReached(
                    f"attempt {attempt} for {inc['id']} refused: limit/ownership/ordering check failed")
            self.repos.transition(c, inc["id"], status)
            s = decision.strategy
            c.execute(
                "INSERT INTO executions (id, incident_id, remediation_id, environment, action, strategy, executor,"
                " attempt, status, started_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (exec_id, inc["id"], rid, inc["environment"], s.action, s.name, self.executors.default,
                 attempt, "running", now))
            self.activity.log(
                "execution_started" if attempt == 1 else "retry_started",
                f"Attempt {attempt}/{MAX_ATTEMPTS}: executing `{s.name}` (simulated)",
                incident_id=inc["id"], action=s.action, status="running", attempt=attempt,
                environment=inc["environment"], details={"execution_id": exec_id, "strategy": s.name})
        return exec_id

    def _execute(self, inc: dict[str, Any], decision: StrategyDecision, attempt: int, exec_id: str) -> ExecutionResult:
        thresholds = self.config.thresholds()
        warn = None if inc["metric"] == "service" else thresholds[inc["metric"]]["warning"]
        req = ExecutionRequest(
            incident_id=inc["id"], attempt=attempt, strategy=decision.strategy, environment=inc["environment"],
            metric=inc["metric"], warning_threshold=warn, epoch=self.sim.epoch,
            plan_outcome=self._plan_outcome(inc, attempt))
        started = utcnow()
        try:
            result = self.executors.get().execute(req)
        except SafetyViolation as exc:
            self.activity.log("safety_violation", str(exc), incident_id=inc["id"], action="execute",
                              status="blocked", attempt=attempt, environment=inc["environment"])
            result = ExecutionResult("failed", "execution blocked by safety guard", error=str(exc))
        except Exception as exc:  # executor bugs/exceptions are recorded, never swallowed
            logger.exception("executor raised for %s attempt %s", inc["id"], attempt)
            result = ExecutionResult("failed", "executor raised an exception", error=f"{type(exc).__name__}: {exc}")
        ended = utcnow()
        self.db.execute(
            "UPDATE executions SET status=?, ended_at=?, duration_ms=?, message=?, error=? WHERE id=?",
            (result.status, ended, duration_ms(started, ended), result.message, result.error, exec_id))
        self.activity.log(
            "execution_completed" if result.status == "success" else "execution_failed",
            f"Attempt {attempt}: `{decision.strategy.name}` {'executed' if result.status == 'success' else 'FAILED'}"
            f" - {result.message}" + (f" [{result.error}]" if result.error else ""),
            incident_id=inc["id"], action=decision.strategy.action, status=result.status, attempt=attempt,
            environment=inc["environment"], details={"execution_id": exec_id, "error": result.error})
        return result

    def _plan_outcome(self, inc: dict[str, Any], attempt: int) -> str | None:
        plan = (inc.get("scenario") or {}).get("plan")
        if plan and attempt - 1 < len(plan):
            return plan[attempt - 1]
        return None

    def _scenario_pre_flight(self, inc: dict[str, Any]) -> None:
        """Demo hook: a scenario may make the fault clear on its own just before remediation begins."""
        sc = inc.get("scenario") or {}
        if sc.get("pre_flight") == "self_recover":
            self.sim.recover_fault(_FAULT_BY_METRIC[inc["metric"]])
            self.activity.log("scenario_event", "Scenario: the simulated fault cleared on its own",
                              incident_id=inc["id"], action="self_recover", status="ok", environment=inc["environment"])

    def _sleep(self) -> bool:
        """Pause between phases (visible progress in the UI). Returns True if shutdown was requested."""
        delay = self.settings.step_delay_seconds
        if delay > 0:
            return self._stop.wait(delay)
        return self._stop.is_set()

    # ------------------------------------------------------------------ decisions
    def _history(self, incident_id: str) -> list[AttemptRecord]:
        recs = []
        for a in self.repos.attempts(incident_id):
            e, v = a["execution"], a["verification"]
            if e is None or e["status"] == "running":
                continue
            recs.append(AttemptRecord(
                attempt=a["attempt"], strategy=a["strategy"], execution_status=e["status"],
                verification_result=v["result"] if v else None, failure_reason=a["failure_reason"],
                before=a["state_before"], after=a["state_after"]))
        return recs

    def _make_decision(self, inc: dict[str, Any], attempt: int, history: list[AttemptRecord]) -> StrategyDecision:
        state = self.verifier.capture()
        metric = inc["metric"]
        thr = self.config.thresholds().get(metric) if metric != "service" else None
        ctx = SelectionContext(
            incident_type=inc["type"], severity=inc["severity"], environment=inc["environment"], metric=metric,
            value=state["service_state"] if metric == "service" else state[metric],
            warning_threshold=thr["warning"] if thr else None, critical_threshold=thr["critical"] if thr else None,
            attempt=attempt, history=history)
        return self.selector.select(ctx)

    @staticmethod
    def _decision_dict(d: StrategyDecision) -> dict[str, Any]:
        return {"strategy": d.strategy.name, "action": d.strategy.action, "reason": d.reason,
                "expected_outcome": d.expected_outcome, "attempt": d.attempt, "ranker": d.ranker,
                "alternatives": d.alternatives}

    def _save_decision(self, c, inc: dict[str, Any], rid: str | None, d: StrategyDecision, log: bool = True) -> None:
        c.execute(
            "INSERT INTO strategy_decisions (id, incident_id, remediation_id, attempt, strategy, reason,"
            " expected_outcome, context_json, previous_outcomes_json, alternatives_json, ranker, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("DEC"), inc["id"], rid, d.attempt, d.strategy.name, d.reason, d.expected_outcome,
             dumps(d.context), dumps(d.previous_outcomes), dumps(d.alternatives), d.ranker, utcnow()))
        if log:
            self.activity.log("strategy_selected", d.reason, incident_id=inc["id"], action=d.strategy.action,
                              status="selected", attempt=d.attempt, environment=inc["environment"],
                              details={"strategy": d.strategy.name, "ranker": d.ranker})

    def _decision_from_row(self, row: dict[str, Any] | None) -> StrategyDecision | None:
        if row is None:
            return None
        from .strategies import get_strategy
        s = get_strategy(row["strategy"])
        return StrategyDecision(strategy=s, reason=row["reason"], expected_outcome=row["expected_outcome"],
                                attempt=row["attempt"], context=row["context"] or {},
                                previous_outcomes=row["previous_outcomes"] or [],
                                alternatives=row["alternatives"] or [], ranker=row["ranker"])

    # ------------------------------------------------------------------ terminal states
    def _resolve(self, incident_id: str, rid: str, *, resolution_type: str, resolution: str) -> None:
        now, final = utcnow(), self.verifier.capture()
        with self.db.tx() as c:
            inc = c.execute("SELECT environment, attempts_made FROM incidents WHERE id=?", (incident_id,)).fetchone()
            self.repos.transition(c, incident_id, "resolved", is_active=0, resolved_at=now, resolution=resolution,
                                  resolution_type=resolution_type, workflow_state="finished",
                                  final_state_json=final, manual_intervention_required=0)
            c.execute("UPDATE remediations SET status='resolved', updated_at=?, completed_at=? WHERE id=?",
                      (now, now, rid))
            self.activity.log("incident_resolved", resolution, incident_id=incident_id, action="resolve",
                              status="resolved", attempt=inc["attempts_made"] or None, environment=inc["environment"],
                              details={"resolution_type": resolution_type, "final_state": final})

    def _escalate(self, incident_id: str, rid: str, reason: str) -> None:
        now, final = utcnow(), self.verifier.capture()
        attempts = self.repos.attempts(incident_id)
        lines = [f"attempt {a['attempt']} `{a['strategy']}`: {a['outcome']}"
                 + (f" ({a['failure_reason']})" if a["failure_reason"] else "") for a in attempts]
        with self.db.tx() as c:
            inc = c.execute("SELECT environment, attempts_made FROM incidents WHERE id=?", (incident_id,)).fetchone()
            existing = self.repos.require_incident(incident_id)
            step = (existing.get("diagnosis") or {}).get("recommended_manual_step") or "Investigate manually."
            self.repos.transition(
                c, incident_id, "escalated", escalated_at=now, manual_intervention_required=1,
                workflow_state="finished", final_state_json=final, resolution_type="escalated",
                resolution=f"Automation stopped: {reason}. Manual intervention required.",
                recommended_action=step)
            c.execute("UPDATE remediations SET status='escalated', updated_at=?, completed_at=? WHERE id=?",
                      (now, now, rid))
            self.activity.log(
                "incident_escalated",
                f"ESCALATED after {inc['attempts_made']} attempt(s): {reason}. Automation stopped; manual "
                f"intervention required. " + " | ".join(lines),
                incident_id=incident_id, action="escalate", status="escalated", attempt=inc["attempts_made"] or None,
                environment=inc["environment"], details={"attempts": lines, "final_state": final,
                                                         "recommended_action": step})
