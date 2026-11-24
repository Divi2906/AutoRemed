"""Incident detection & lifecycle: healthy/warning/critical/duplicate/recovered, real-vs-sim separation."""
from __future__ import annotations

from app.core.util import ENV_REAL, ENV_SIM
from app.remediation.executors import TestExecutor


def use_noop_executor(c):
    """Executor that 'succeeds' without touching state, so incidents stay observable."""
    c.executors.register(TestExecutor(outcomes=["fail"] * 50))
    c.executors.default = "test"


def active(c, env=ENV_SIM):
    return c.repos.active_incidents(env)


def test_healthy_metrics_create_no_incident(container):
    container.monitor.tick()
    assert container.repos.list_incidents()[1] == 0


def test_warning_threshold_creates_warning_incident(container):
    use_noop_executor(container)
    container.sim.inject_fault("cpu", 80)         # warning is 75, critical 90
    container.monitor.tick()
    inc, = active(container)
    assert inc["severity"] == "warning" and inc["type"] and inc["metric"] == "cpu"
    assert inc["environment"] == ENV_SIM and inc["fingerprint"]
    assert inc["diagnosis"]["probable_root_cause"] and inc["root_cause"]


def test_critical_threshold_creates_critical_incident(container):
    use_noop_executor(container)
    container.sim.inject_fault("disk", 97)
    container.monitor.tick()
    inc, = active(container)
    assert inc["severity"] == "critical" and inc["metric"] == "disk"
    assert inc["threshold"] == 95.0 and inc["value"] == 97.0


def test_repeated_detection_creates_no_duplicates(container):
    use_noop_executor(container)
    container.sim.inject_fault("cpu", 96)
    for _ in range(6):
        container.monitor.tick()
    assert container.repos.list_incidents()[1] == 1
    # and exactly one remediation workflow ran (3 attempts max), not 6
    assert len(container.repos.executions(active(container)[0]["id"] if active(container) else
                                          container.repos.list_incidents()[0][0]["id"])[0]) <= 3


def test_severity_upgrades_without_new_incident(container):
    use_noop_executor(container)
    container.sim.inject_fault("memory", 85)
    container.monitor.tick()
    container.sim.set_metric("memory", 95)
    container.monitor.tick()
    items, total = container.repos.list_incidents()
    assert total == 1 and items[0]["severity"] == "critical"


def test_recovery_detected_closes_incident_without_action(container):
    container.config.set_mode("approval")          # nothing executes, incident stays open
    container.sim.inject_fault("cpu", 96)
    container.monitor.tick()
    inc, = active(container)
    assert inc["status"] == "pending_approval"
    container.sim.recover_fault("cpu")
    container.monitor.tick()
    done = container.repos.incident(inc["id"])
    assert done["status"] == "resolved" and not done["is_active"]
    assert done["resolution_type"] == "recovered_before_remediation"
    assert container.repos.executions(inc["id"])[1] == 0
    assert container.repos.remediation_for_incident(inc["id"])["status"] == "cancelled"


def test_new_incident_possible_after_resolution(container):
    for _ in range(2):
        container.sim.inject_fault("cpu", 96)
        container.monitor.tick()
        container.monitor.tick()
        container.sim.recover_fault("cpu")
        container.monitor.tick()
    assert container.repos.list_incidents()[1] == 2


def test_lifecycle_statuses_are_recorded_in_activity_log(container):
    container.demo.trigger("second_attempt_succeeds", "cpu")
    events = [r["event_type"] for r in container.activity.query(limit=500)[0]]
    for expected in ("incident_detected", "diagnosis", "strategy_selected", "execution_started",
                     "execution_failed", "retry_scheduled", "retry_started", "verification", "incident_resolved"):
        assert expected in events, expected


def test_real_host_incident_is_observe_only_and_never_remediated(container_fake, fake_real):
    c = container_fake
    fake_real.cpu = 97.0
    before = c.sim.snapshot()
    c.monitor.tick(); c.monitor.tick()
    assert c.repos.active_incidents(ENV_REAL) == []     # transient-spike guard: 3 consecutive samples needed
    c.monitor.tick()
    inc, = c.repos.active_incidents(ENV_REAL)
    assert inc["environment"] == ENV_REAL and inc["observe_only"] is True
    assert c.repos.executions(inc["id"])[1] == 0
    assert c.repos.remediation_for_incident(inc["id"]) is None
    assert c.sim.snapshot() == before             # simulation untouched by a real-host event
    fake_real.cpu = 10.0
    c.monitor.tick()
    assert not c.repos.incident(inc["id"])["is_active"]


def test_simulation_fault_never_creates_real_host_incident(container_fake):
    container_fake.sim.inject_fault("cpu", 96)
    container_fake.monitor.tick()
    assert container_fake.repos.active_incidents(ENV_REAL) == []


def test_consecutive_violation_rule_suppresses_transient_spike(container):
    use_noop_executor(container)
    container.config.set_consecutive(ENV_SIM, 3)
    container.sim.inject_fault("cpu", 96)
    container.monitor.tick(); container.monitor.tick()
    assert container.repos.list_incidents()[1] == 0
    container.sim.recover_fault("cpu")             # spike ends -> counter resets
    container.monitor.tick()
    container.sim.inject_fault("cpu", 96)
    container.monitor.tick(); container.monitor.tick()
    assert container.repos.list_incidents()[1] == 0
    container.monitor.tick()
    assert container.repos.list_incidents()[1] == 1


def test_service_failure_incident(container):
    container.demo.trigger("first_attempt_succeeds", "service")
    inc = container.repos.list_incidents()[0][0]
    assert inc["metric"] == "service" and inc["status"] == "resolved"
    assert container.sim.snapshot()["service_state"] == "running"
