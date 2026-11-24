"""Attempt-limit enforcement under concurrency, simultaneous incidents, restart/persistence."""
from __future__ import annotations

import threading

import pytest

from app.container import Container
from app.core.errors import AttemptLimitReached
from app.remediation.strategies import get_strategy
from tests.conftest import executions_of, make_settings, run


def hammer(fn, n=12):
    barrier, errors, results = threading.Barrier(n), [], []

    def w():
        barrier.wait()
        try:
            results.append(fn())
        except Exception as e:      # noqa: BLE001 - collected for assertions
            errors.append(e)
    ts = [threading.Thread(target=w) for _ in range(n)]
    [t.start() for t in ts]; [t.join() for t in ts]
    return results, errors


def test_concurrent_workflow_starts_run_only_one_workflow(async_container):
    c = async_container
    res = c.demo.trigger("all_attempts_fail", "cpu")
    hammer(lambda: c.orchestrator.run_workflow(res["incident_id"]))
    for _ in range(5):
        c.orchestrator.dispatch_pending()
    assert c.orchestrator.wait_idle(30)
    inc = c.repos.incident(res["incident_id"])
    ex = executions_of(c, res["incident_id"])
    assert len(ex) == 3 and sorted(e["attempt"] for e in ex) == [1, 2, 3]
    assert inc["status"] == "escalated" and inc["attempts_made"] == 3


def test_concurrent_attempt_reservation_cannot_bypass_limit(container):
    c = container
    inc = run(c, "approval_required")
    rem = c.repos.remediation_for_incident(inc["id"])
    c.db.execute("UPDATE incidents SET workflow_state='running', status='approved' WHERE id=?", (inc["id"],))
    inc = c.repos.incident(inc["id"])
    dec = c.orchestrator._decision_from_row(c.repos.decision(inc["id"], 1))
    results, errors = hammer(lambda: c.orchestrator._reserve_attempt(inc, rem["id"], dec, 1), n=16)
    assert len(results) == 1 and all(isinstance(e, AttemptLimitReached) for e in errors)
    assert c.repos.incident(inc["id"])["attempts_made"] == 1


def test_fourth_attempt_is_refused_by_backend_and_schema(container):
    c = container
    inc = run(c, "all_attempts_fail")
    rem = c.repos.remediation_for_incident(inc["id"])
    c.db.execute("UPDATE incidents SET workflow_state='running' WHERE id=?", (inc["id"],))
    dec = c.orchestrator._make_decision(c.repos.incident(inc["id"]), 4, [])
    with pytest.raises(AttemptLimitReached):
        c.orchestrator._reserve_attempt(c.repos.incident(inc["id"]), rem["id"], dec, 4)
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):          # DB CHECK(attempt BETWEEN 1 AND 3)
        with c.db.tx() as cx:
            cx.execute("INSERT INTO executions (id, incident_id, remediation_id, environment, action, strategy,"
                       " executor, attempt, status, started_at) VALUES ('E4',?,?,'simulation','a','s','x',4,'running','t')",
                       (inc["id"], rem["id"]))
    assert len(executions_of(c, inc["id"])) == 3


def test_simultaneous_cpu_and_memory_incidents(async_container):
    c = async_container
    a = c.demo.trigger("first_attempt_succeeds", "cpu")
    b = c.demo.trigger("all_attempts_fail", "memory")
    assert c.orchestrator.wait_idle(30)
    ia, ib = c.repos.incident(a["incident_id"]), c.repos.incident(b["incident_id"])
    assert (ia["status"], len(executions_of(c, ia["id"]))) == ("resolved", 1)
    assert (ib["status"], len(executions_of(c, ib["id"]))) == ("escalated", 3)


def test_same_fault_repeatedly_detected_during_remediation(async_container):
    c = async_container
    res = c.demo.trigger("third_attempt_succeeds", "disk")
    for _ in range(20):
        c.monitor.tick()
    assert c.orchestrator.wait_idle(30)
    assert c.repos.list_incidents()[1] == 1
    assert len(executions_of(c, res["incident_id"])) == 3


# ------------------------------------------------------------------ persistence
def reopen(tmp_path, **kw) -> Container:
    return Container(make_settings(tmp_path, **kw))


def test_history_survives_restart(tmp_path):
    c1 = reopen(tmp_path)
    a = run(c1, "all_attempts_fail", "cpu")
    b = run(c1, "second_attempt_succeeds", "memory")
    n_logs = c1.activity.query(limit=1)[1]
    c1.monitor.tick()
    c1.config.set_thresholds({"cpu": {"warning": 70, "critical": 88}})
    c1.shutdown()

    c2 = reopen(tmp_path)
    ia, ib = c2.repos.incident(a["id"]), c2.repos.incident(b["id"])
    assert ia["status"] == "escalated" and ia["attempts_made"] == 3 and ia["manual_intervention_required"]
    assert ib["status"] == "resolved" and ib["attempts_made"] == 2
    assert len(executions_of(c2, a["id"])) == 3 and len(c2.repos.verifications(a["id"])[0]) == 3
    assert c2.activity.query(limit=1)[1] >= n_logs
    assert c2.config.thresholds()["cpu"] == {"warning": 70.0, "critical": 88.0}
    assert len(c2.monitor.history("simulation", 10)) >= 1
    c2.start()                                            # restart must not re-run finished workflows
    assert len(executions_of(c2, a["id"])) == 3
    c2.shutdown()


class Crash(BaseException):
    pass


def test_attempt_count_preserved_and_workflow_resumed_after_crash(tmp_path):
    from app.remediation.executors import TestExecutor
    c1 = reopen(tmp_path)
    c1.executors.register(TestExecutor(outcomes=[lambda r: (_ for _ in ()).throw(Crash())]))
    c1.executors.default = "test"
    with pytest.raises(Crash):
        c1.demo.inject("cpu")
    inc = c1.repos.list_incidents()[0][0]
    # emulate process death: the 'finally' never ran
    c1.db.execute("UPDATE incidents SET workflow_state='running' WHERE id=?", (inc["id"],))
    assert c1.repos.incident(inc["id"])["attempts_made"] == 1
    c1.shutdown()

    c2 = reopen(tmp_path)
    c2.start()                                            # resume_after_restart
    after = c2.repos.incident(inc["id"])
    ex = sorted(executions_of(c2, inc["id"]), key=lambda e: e["attempt"])
    assert ex[0]["attempt"] == 1 and ex[0]["status"] == "failed" and "restart" in ex[0]["error"]
    assert after["attempts_made"] <= 3 and len(ex) <= 3 and len(ex) >= 2   # continued from attempt 2, not 1
    assert after["status"] in ("resolved", "escalated")
    assert len({e["attempt"] for e in ex}) == len(ex)
    c2.shutdown()


def test_demo_reset_resets_simulation_but_keeps_history(container):
    inc = run(container, "all_attempts_fail")
    logs_before = container.activity.query(limit=1)[1]
    container.demo.reset()
    assert container.sim.snapshot()["cpu"] == 22.0
    kept = container.repos.incident(inc["id"])
    assert kept is not None and kept["attempts_made"] == 3 and not kept["is_active"]
    assert len(executions_of(container, inc["id"])) == 3
    assert container.activity.query(limit=1)[1] > logs_before
    assert container.repos.active_incidents("simulation") == []


def test_reset_cancels_pending_approval_incident(container):
    inc = run(container, "approval_required")
    container.demo.reset()
    assert container.repos.incident(inc["id"])["status"] == "cancelled"
    assert executions_of(container, inc["id"]) == []
