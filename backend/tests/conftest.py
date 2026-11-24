from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.container import Container
from app.core.util import utcnow
from app.monitoring.sources import Snapshot
from app.settings import Settings


def make_settings(tmp_path, **kw) -> Settings:
    base = dict(db_path=str(tmp_path / "test.db"), autostart_monitoring=False, step_delay_seconds=0.0,
                sync_dispatch=True)
    base.update(kw)
    return Settings(**base)


class FakeRealSource:
    """Controllable stand-in for the real host (only used to test the real-host code path)."""

    environment = "real_host"

    def __init__(self, cpu=10.0, memory=30.0, disk=40.0):
        self.cpu, self.memory, self.disk = cpu, memory, disk
        self.fail = False

    def collect(self) -> Snapshot:
        if self.fail:
            raise RuntimeError("boom")
        return Snapshot("real_host", utcnow(), self.cpu, self.memory, self.disk, None, [])


@pytest.fixture
def container(tmp_path):
    # Host metrics are pinned to a healthy fake so results never depend on the machine running the tests.
    c = Container(make_settings(tmp_path), real_source=FakeRealSource())
    yield c
    c.shutdown()


@pytest.fixture
def fake_real():
    return FakeRealSource()


@pytest.fixture
def container_fake(tmp_path, fake_real):
    c = Container(make_settings(tmp_path), real_source=fake_real)
    yield c
    c.shutdown()


@pytest.fixture
def async_container(tmp_path):
    """Remediation workflows run in the thread pool (used for real concurrency tests)."""
    c = Container(make_settings(tmp_path, sync_dispatch=False, step_delay_seconds=0.03),
                  real_source=FakeRealSource())
    yield c
    c.shutdown()


@pytest.fixture
def client(container):
    return TestClient(create_app(container))


def executions_of(c: Container, incident_id: str) -> list[dict]:
    return c.repos.executions(incident_id)[0]


def run(c: Container, scenario: str, fault: str = "cpu") -> dict:
    res = c.demo.trigger(scenario, fault)
    return c.repos.incident(res["incident_id"])
