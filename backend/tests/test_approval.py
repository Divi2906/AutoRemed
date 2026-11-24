"""Approval Mode: pending / approve / reject / history; rejected actions never execute."""
from __future__ import annotations

import pytest

from app.core.errors import Conflict
from tests.conftest import executions_of, run


def pending(c, fault="cpu"):
    inc = run(c, "approval_required", fault)
    rem = c.repos.remediation_for_incident(inc["id"])
    return inc, rem


def test_proposal_has_strategy_and_reasoning_and_nothing_executes(container):
    inc, rem = pending(container)
    assert inc["status"] == "pending_approval" and rem["approval_state"] == "pending"
    assert rem["proposed_strategy"] and rem["proposal"]["reason"]
    assert executions_of(container, inc["id"]) == []
    container.monitor.tick(); container.orchestrator.dispatch_pending()
    assert executions_of(container, inc["id"]) == []                 # still nothing without approval


def test_approved_action_executes_and_resolves(container):
    inc, rem = pending(container)
    container.orchestrator.approve(rem["id"], actor="alice", note="go")
    after = container.repos.incident(inc["id"])
    assert after["status"] == "resolved" and after["attempts_made"] == 1
    assert len(executions_of(container, inc["id"])) == 1
    acts = [a["action"] for a in container.repos.approvals(incident_id=inc["id"])]
    assert acts == ["requested", "approved"]
    events = [r["event_type"] for r in container.activity.query(incident_id=inc["id"], limit=200)[0]]
    assert "approval_requested" in events and "approval_approved" in events


def test_rejected_action_never_executes(container):
    inc, rem = pending(container)
    container.orchestrator.reject(rem["id"], actor="bob", note="too risky")
    after = container.repos.incident(inc["id"])
    assert after["status"] == "rejected" and after["manual_intervention_required"] is True
    for _ in range(3):
        container.monitor.tick(); container.orchestrator.dispatch_pending()
    assert container.orchestrator.run_workflow(inc["id"]) is None
    assert executions_of(container, inc["id"]) == [] and after["attempts_made"] == 0
    assert [a["action"] for a in container.repos.approvals(incident_id=inc["id"])] == ["requested", "rejected"]
    events = [r["event_type"] for r in container.activity.query(incident_id=inc["id"], limit=200)[0]]
    assert "approval_rejected" in events


def test_action_rejected_scenario_zero_executions(container):
    inc = run(container, "action_rejected")
    assert inc["status"] == "rejected" and executions_of(container, inc["id"]) == []


def test_double_decision_is_refused_and_creates_no_duplicate_workflow(container):
    inc, rem = pending(container)
    container.orchestrator.approve(rem["id"])
    with pytest.raises(Conflict):
        container.orchestrator.approve(rem["id"])
    with pytest.raises(Conflict):
        container.orchestrator.reject(rem["id"])
    assert len(executions_of(container, inc["id"])) == 1


def test_approval_does_not_bypass_retry_limit(container):
    inc = run(container, "approval_required")           # plan = [recover]; override to force failures
    c = container
    rem = c.repos.remediation_for_incident(inc["id"])
    from app.remediation.executors import TestExecutor
    c.executors.register(TestExecutor(outcomes=["fail"] * 10)); c.executors.default = "test"
    c.orchestrator.approve(rem["id"])
    after = c.repos.incident(inc["id"])
    assert after["status"] == "escalated" and after["attempts_made"] == 3
    assert len(executions_of(c, inc["id"])) == 3


def test_approval_mode_config_applies_to_new_incidents(container):
    container.config.set_mode("approval")
    container.demo.inject("memory")
    inc = container.repos.list_incidents()[0][0]
    assert inc["mode"] == "approval" and inc["status"] == "pending_approval"
    assert executions_of(container, inc["id"]) == []
