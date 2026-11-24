from __future__ import annotations

import time

import pytest

from app.core.errors import ValidationFailed
from app.monitoring.health import classify, metric_statuses, overall
from app.monitoring.sources import RealHostSource


class FakePsutil:
    def __init__(self, fail=()):
        self.fail = set(fail)

    def cpu_percent(self, interval=None):
        if "cpu" in self.fail:
            raise OSError("cpu unavailable")
        return 12.5

    def virtual_memory(self):
        if "memory" in self.fail:
            raise OSError("memory unavailable")

        class M:
            percent = 55.0
        return M()

    def disk_usage(self, path):
        class D:
            percent = 61.0
        return D()


def test_real_host_source_reads_actual_psutil_values():
    snap = RealHostSource(cache_seconds=0).collect()
    assert snap.environment == "real_host"
    for v in (snap.cpu, snap.memory, snap.disk):
        assert v is not None and 0.0 <= v <= 100.0
    assert snap.errors == [] and snap.service_state is None


def test_unavailable_metric_is_reported_not_fatal():
    snap = RealHostSource(psutil_module=FakePsutil(fail={"memory"}), cache_seconds=0).collect()
    assert snap.memory is None and snap.cpu == 12.5 and snap.disk == 61.0
    assert len(snap.errors) == 1 and "memory" in snap.errors[0]


@pytest.mark.parametrize("value,expected", [(10, "ok"), (74.9, "ok"), (75, "warning"), (89.9, "warning"),
                                            (90, "critical"), (100, "critical"), (None, "unknown")])
def test_classify_cpu_defaults(value, expected):
    assert classify(value, 75, 90) == expected


def test_overall_health_is_worst_status():
    assert overall({"cpu": "ok", "memory": "warning", "disk": "ok"}) == "warning"
    assert overall({"cpu": "ok", "memory": "critical"}) == "critical"
    assert overall({"cpu": "unknown"}) == "unknown"


def test_default_thresholds_match_spec(container):
    t = container.config.thresholds()
    assert t["cpu"] == {"warning": 75.0, "critical": 90.0}
    assert t["memory"] == {"warning": 80.0, "critical": 90.0}
    assert t["disk"] == {"warning": 85.0, "critical": 95.0}


def test_thresholds_are_configurable_and_validated(container):
    container.config.set_thresholds({"cpu": {"warning": 50, "critical": 60}})
    assert container.config.thresholds()["cpu"] == {"warning": 50.0, "critical": 60.0}
    st = metric_statuses({"cpu": 55.0, "memory": 10, "disk": 10, "service_state": None}, container.config.thresholds())
    assert st["cpu"] == "warning"
    with pytest.raises(ValidationFailed):
        container.config.set_thresholds({"cpu": {"warning": 95, "critical": 90}})
    with pytest.raises(ValidationFailed):
        container.config.set_thresholds({"bogus": {"warning": 1, "critical": 2}})


def test_tick_persists_both_environments_separately(container):
    container.monitor.tick()
    container.monitor.tick()
    real = container.monitor.history("real_host")
    sim = container.monitor.history("simulation")
    assert len(real) == 2 and len(sim) == 2
    assert all(r["environment"] == "real_host" for r in real)
    assert all(r["environment"] == "simulation" for r in sim)
    # the baseline simulation values are deterministic and clearly not the host's psutil values
    assert sim[-1]["cpu"] == 22.0 and sim[-1]["service_state"] == "running"
    assert real[-1]["service_state"] is None
    assert sim[0]["ts"] <= sim[1]["ts"]


def test_healthy_state_creates_no_incident(container):
    container.monitor.tick()
    assert container.repos.list_incidents(environment="simulation")[1] == 0


def test_loop_start_stop_and_no_duplicate_loops(container):
    m = container.monitor
    assert m.start(interval_seconds=1) is True
    assert m.start() is False and m.start() is False          # no second loop
    assert m.status()["thread_count"] == 1 and m.running
    deadline = time.time() + 5
    while m.tick_count < 1 and time.time() < deadline:
        time.sleep(0.05)
    assert m.tick_count >= 1
    assert m.stop() is True
    assert not m.running and m.status()["thread_count"] == 0
    assert m.stop() is False                                   # already stopped
    # restartable
    assert m.start() is True and m.status()["thread_count"] == 1
    m.stop()


def test_collection_error_does_not_break_the_loop_or_other_environment(container_fake, fake_real):
    c = container_fake
    fake_real.fail = True
    c.monitor.tick()  # must not raise
    assert c.monitor.error_count == 1 and "real_host" in c.monitor.last_error
    assert len(c.monitor.history("simulation")) == 1           # simulation still collected
    events = [r["event_type"] for r in c.activity.query()[0]]
    assert "monitor_error" in events


def test_unavailable_metric_never_creates_an_incident(container_fake, fake_real):
    fake_real.cpu = None
    for _ in range(5):
        container_fake.monitor.tick()
    assert container_fake.repos.list_incidents(environment="real_host")[1] == 0


def test_transient_real_host_spike_does_not_create_incident(container_fake, fake_real):
    c = container_fake
    fake_real.cpu = 97.0
    c.monitor.tick()
    c.monitor.tick()                      # 2 consecutive < 3 required
    assert c.repos.list_incidents(environment="real_host")[1] == 0
    fake_real.cpu = 20.0
    c.monitor.tick()                      # spike ended: counter resets
    fake_real.cpu = 97.0
    c.monitor.tick()
    c.monitor.tick()
    assert c.repos.list_incidents(environment="real_host")[1] == 0
    c.monitor.tick()                      # now 3 consecutive
    assert c.repos.list_incidents(environment="real_host")[1] == 1


def test_real_host_incident_is_observe_only_and_never_remediated(container_fake, fake_real):
    c = container_fake
    fake_real.cpu = 99.0
    for _ in range(6):
        c.monitor.tick()
    items, total = c.repos.list_incidents(environment="real_host")
    assert total == 1                      # deduplicated across repeated detections
    inc = items[0]
    assert inc["observe_only"] is True and inc["environment"] == "real_host"
    assert c.orchestrator.run_workflow(inc["id"]) is None      # refuses to claim
    assert c.repos.executions(inc["id"])[1] == 0
    assert c.repos.remediation_for_incident(inc["id"]) is None
    assert "never" in inc["diagnosis"]["recommended_manual_step"].lower()
    # and it closes by itself when the host recovers
    fake_real.cpu = 10.0
    c.monitor.tick()
    closed = c.repos.incident(inc["id"])
    assert closed["is_active"] is False and closed["status"] == "resolved"


def test_monitoring_state_changes_are_logged(container):
    container.monitor.start(interval_seconds=1)
    container.monitor.stop()
    events = [r["event_type"] for r in container.activity.query(limit=50)[0]]
    assert "monitoring_started" in events and "monitoring_stopped" in events
