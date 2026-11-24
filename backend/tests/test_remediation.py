"""Executors, independent verification, retry workflow, escalation, safety."""
from __future__ import annotations

import pytest

from app.core.errors import ExecutorDisabled, SafetyViolation
from app.remediation.executors import ExecutionRequest, SimulationExecutor, TestExecutor
from app.remediation.strategies import get_strategy
from tests.conftest import executions_of, run

SCENARIO_EXPECT = {
    "first_attempt_succeeds": ("resolved", 1),
    "second_attempt_succeeds": ("resolved", 2),
    "third_attempt_succeeds": ("resolved", 3),
    "all_attempts_fail": ("escalated", 3),
    "verification_fails": ("resolved", 2),
    "recovers_before_remediation": ("resolved", 0),
}


@pytest.mark.parametrize("fault", ["cpu", "memory", "disk", "service"])
@pytest.mark.parametrize("scenario,expected", SCENARIO_EXPECT.items())
def test_scenarios_end_state_and_exact_execution_count(container, scenario, expected, fault):
    inc = run(container, scenario, fault)
    status, n = expected
    assert inc["status"] == status
    assert inc["attempts_made"] == n == len(executions_of(container, inc["id"]))
    assert not inc["is_active"] or status == "escalated" or inc["manual_intervention_required"]


def test_success_stops_immediately_and_state_really_changed(container):
    inc = run(container, "first_attempt_succeeds")
    assert inc["status"] == "resolved" and inc["attempts_made"] == 1
    assert container.sim.snapshot()["cpu"] < 75                   # the simulated state truly recovered
    vers = container.repos.verifications(inc["id"])[0]
    assert len(vers) == 1 and vers[0]["result"] == "recovered"
    assert inc["resolution_type"] == "remediated"


def test_escalation_after_exactly_three_attempts(container):
    inc = run(container, "all_attempts_fail")
    assert inc["status"] == "escalated" and inc["manual_intervention_required"] is True
    assert inc["attempts_made"] == 3 and len(executions_of(container, inc["id"])) == 3
    assert inc["recommended_action"] and inc["resolution"]
    assert inc["is_active"]                                        # stays visible until a human acts
    attempts = container.repos.attempts(inc["id"])
    assert [a["attempt"] for a in attempts] == [1, 2, 3] and all(a["failure_reason"] for a in attempts)
    events = [r["event_type"] for r in container.activity.query(incident_id=inc["id"], limit=500)[0]]
    assert "incident_escalated" in events
    # automation really stopped: another workflow run and monitoring passes execute nothing more
    container.orchestrator.run_workflow(inc["id"])
    container.orchestrator.dispatch_pending()
    container.monitor.tick(); container.monitor.tick()
    assert len(executions_of(container, inc["id"])) == 3


def test_attempt_records_distinguish_the_three_outcomes(container):
    inc = run(container, "third_attempt_succeeds")
    a1, a2, a3 = container.repos.attempts(inc["id"])
    assert a1["execution"]["status"] == "failed"                                    # execution failed
    assert a2["execution"]["status"] == "success" and a2["verification"]["result"] == "not_recovered"
    assert a3["execution"]["status"] == "success" and a3["verification"]["result"] == "recovered"
    assert a1["outcome"] != a2["outcome"] != a3["outcome"]


def test_execution_record_fields(container):
    inc = run(container, "second_attempt_succeeds")
    e1, e2 = sorted(executions_of(container, inc["id"]), key=lambda e: e["attempt"])
    for e in (e1, e2):
        assert e["id"].startswith("EXE") and e["incident_id"] == inc["id"] and e["environment"] == "simulation"
        assert e["strategy"] and e["action"] and e["started_at"] and e["ended_at"] and e["duration_ms"] is not None
    assert e1["status"] == "failed" and e1["error"] and e2["status"] == "success"
    assert e1["strategy"] != e2["strategy"]


def test_verification_record_fields(container):
    inc = run(container, "verification_fails")
    v1, v2 = sorted(container.repos.verifications(inc["id"])[0], key=lambda v: v["attempt"])
    assert v1["result"] == "not_recovered" and v1["failure_reason"]
    assert v1["before"]["cpu"] > v1["after"]["cpu"] >= 75        # improved but not enough
    assert v1["criteria"]["rule"] and v2["result"] == "recovered" and v2["failure_reason"] is None


def test_verifier_does_not_trust_executor_success(container):
    c = container
    c.executors.register(TestExecutor(outcomes=["success", "success", "success"]))   # claims success, changes nothing
    c.executors.default = "test"
    c.demo.inject("cpu")
    inc = c.repos.list_incidents()[0][0]
    assert inc["status"] == "escalated" and inc["attempts_made"] == 3
    assert all(e["status"] == "success" for e in executions_of(c, inc["id"]))      # executor said success...
    assert all(v["result"] == "not_recovered" for v in c.repos.verifications(inc["id"])[0])   # ...verifier disagreed


def test_verifier_catches_executor_failure_with_healthy_state(container):
    c = container
    c.executors.register(TestExecutor(outcomes=[lambda req: (c.sim.recover_fault("cpu"),
                                                             __import__("app.remediation.executors", fromlist=["x"]
                                                                        ).ExecutionResult("failed", "claimed failure", "err"))[1]]))
    c.executors.default = "test"
    c.demo.inject("cpu")
    inc = c.repos.list_incidents()[0][0]
    assert inc["status"] == "resolved" and inc["attempts_made"] == 1            # truth = independent state check


def test_executor_exception_is_recorded_not_swallowed(container):
    c = container
    c.executors.register(TestExecutor(outcomes=["raise", "success"], effect=lambda r: c.sim.recover_fault("cpu")))
    c.executors.default = "test"
    c.demo.inject("cpu")
    inc = c.repos.list_incidents()[0][0]
    e1 = sorted(executions_of(c, inc["id"]), key=lambda e: e["attempt"])[0]
    assert e1["status"] == "failed" and "RuntimeError" in e1["error"]
    assert inc["status"] == "resolved" and inc["attempts_made"] == 2


def test_recovery_before_remediation_executes_nothing(container):
    inc = run(container, "recovers_before_remediation")
    assert inc["resolution_type"] == "recovered_before_remediation"
    assert executions_of(container, inc["id"]) == []


def test_multiple_faults_do_not_corrupt_each_other(container):
    a = run(container, "first_attempt_succeeds", "cpu")
    b = run(container, "all_attempts_fail", "memory")
    assert (a["status"], a["attempts_made"]) == ("resolved", 1)
    assert (b["status"], b["attempts_made"]) == ("escalated", 3)
    assert {e["incident_id"] for e in executions_of(container, a["id"])} == {a["id"]}


# ------------------------------------------------------------------ safety
def test_executor_refuses_real_host_environment(container):
    ex = SimulationExecutor(container.sim)
    req = ExecutionRequest(incident_id="X", attempt=1, strategy=get_strategy("workload_reduction"),
                           environment="real_host", metric="cpu", warning_threshold=75, epoch=0)
    with pytest.raises(SafetyViolation):
        ex.execute(req)


def test_real_executor_is_permanently_disabled(container):
    with pytest.raises(ExecutorDisabled):
        container.executors.get("real").execute(None)


def test_no_shell_or_destructive_calls_in_source():
    import pathlib, re
    root = pathlib.Path(__file__).resolve().parent.parent / "app"
    banned = re.compile(r"\b(subprocess|os\.system|os\.remove|os\.kill|shutil\.rmtree|\.terminate\(|psutil\.Process)\b")
    offenders = [str(p) for p in root.rglob("*.py") if banned.search(p.read_text())]
    assert offenders == []


# ------------------------------------------------------------------ safety-blocked execution
def test_safety_blocked_execution_is_not_retried(container):
    """A SafetyViolation on attempt 1 must escalate immediately; no second attempt is made."""
    from app.core.errors import SafetyViolation

    c = container

    def _raise_safety(req):
        raise SafetyViolation("test: refusing to act outside sandbox")

    c.executors.register(TestExecutor(outcomes=[_raise_safety]))
    c.executors.default = "test"
    c.demo.inject("cpu")
    inc = c.repos.list_incidents()[0][0]

    # Exactly one execution row was created (the blocked attempt).
    execs = executions_of(c, inc["id"])
    assert len(execs) == 1, f"expected 1 execution row, got {len(execs)}"
    assert execs[0]["status"] == "blocked"
    assert "safety" in (execs[0]["error"] or "").lower() or "safety" in (execs[0]["message"] or "").lower()

    # Incident escalated, not left for retry.
    assert inc["status"] == "escalated"
    assert inc["manual_intervention_required"] is True
    assert inc["attempts_made"] == 1  # one attempt was consumed, not three

    # Activity log must contain both safety_violation and execution_blocked events.
    events = [r["event_type"] for r in c.activity.query(incident_id=inc["id"], limit=500)[0]]
    assert "safety_violation" in events
    assert "execution_blocked" in events
    assert "incident_escalated" in events

    # No further attempts if orchestrator or monitor runs again.
    c.orchestrator.run_workflow(inc["id"])
    c.orchestrator.dispatch_pending()
    assert len(executions_of(c, inc["id"])) == 1


def test_safety_blocked_on_second_attempt_does_not_retry_further(container):
    """Ordinary failure on attempt 1, SafetyViolation on attempt 2 → escalate after 2 attempts, no third."""
    from app.core.errors import SafetyViolation

    c = container

    def _raise_safety(req):
        raise SafetyViolation("test: sandbox boundary exceeded on retry")

    # Attempt 1: ordinary executor failure (no state change → verifier sees not_recovered → retry).
    # Attempt 2: SafetyViolation → must escalate immediately.
    c.executors.register(TestExecutor(outcomes=["fail", _raise_safety]))
    c.executors.default = "test"
    c.demo.inject("cpu")
    inc = c.repos.list_incidents()[0][0]

    execs = sorted(executions_of(c, inc["id"]), key=lambda e: e["attempt"])
    assert len(execs) == 2, f"expected 2 execution rows, got {len(execs)}"
    assert execs[0]["status"] == "failed"   # ordinary failure
    assert execs[1]["status"] == "blocked"  # safety block

    assert inc["status"] == "escalated"
    assert inc["attempts_made"] == 2        # stopped at 2, not 3
    assert inc["manual_intervention_required"] is True

    events = [r["event_type"] for r in c.activity.query(incident_id=inc["id"], limit=500)[0]]
    assert "safety_violation" in events
    assert "execution_blocked" in events
    assert "incident_escalated" in events
