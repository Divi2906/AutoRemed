"""Dependency container: wires every service together (modular monolith)."""
from __future__ import annotations

import logging

from .core.activity import ActivityLog
from .core.config_service import ConfigService
from .core.db import Database
from .demo.service import DemoService
from .incidents.diagnosis import DiagnosisEngine
from .incidents.engine import IncidentEngine
from .incidents.repository import Repositories
from .monitoring.monitor import Monitor
from .monitoring.sources import MetricSource, RealHostSource, SimulatedSource
from .remediation.executors import ExecutorRegistry, RealExecutor, SimulationExecutor, TestExecutor
from .remediation.orchestrator import RemediationOrchestrator
from .remediation.strategies import StrategySelector, build_ranker
from .remediation.verifier import HealthVerifier
from .settings import Settings
from .simulation.state import SimulationState

logger = logging.getLogger("autoremed")


class Container:
    def __init__(self, settings: Settings, *, real_source: MetricSource | None = None):
        self.settings = settings
        self.db = Database(settings.db_path)
        self.activity = ActivityLog(self.db)
        self.config = ConfigService(self.db, self.activity)
        self.repos = Repositories(self.db)
        self.sim = SimulationState(self.db)

        # Two strictly separate metric environments. `real_source` is injectable for tests only.
        self.sources = {
            "real_host": real_source or RealHostSource(settings.host_disk_path),
            "simulation": SimulatedSource(self.sim),
        }
        self.diagnosis = DiagnosisEngine()
        self.engine = IncidentEngine(self.db, self.repos, self.config, self.activity, self.diagnosis, self.sim)

        ranker, note = build_ranker(self.config.get("ranker"))
        self.selector = StrategySelector(ranker, note)
        self.executors = ExecutorRegistry("simulation")
        self.executors.register(SimulationExecutor(self.sim))
        self.executors.register(TestExecutor())
        self.executors.register(RealExecutor())
        self.verifier = HealthVerifier(self.db, self.config, self.activity, self.sim.snapshot)
        self.orchestrator = RemediationOrchestrator(
            self.db, self.repos, self.config, self.activity, self.engine, self.selector, self.executors,
            self.verifier, self.sim, settings)
        self.engine.on_created = self.orchestrator.handle_new_incident

        self.monitor = Monitor(
            self.db, self.config, self.activity, self.sources, self.engine.process_snapshot,
            after_tick=self.orchestrator.dispatch_pending, retention=settings.metrics_retention)
        self.demo = DemoService(self.db, self.repos, self.activity, self.sim, self.monitor, self.orchestrator)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        resumed = self.orchestrator.resume_after_restart()
        if resumed:
            logger.info("resumed %s workflow(s) after restart", resumed)
        if self.settings.autostart_monitoring and self.config.monitoring()["enabled"]:
            self.monitor.start()

    def shutdown(self) -> None:
        self.monitor.shutdown()
        self.orchestrator.shutdown()
        self.db.close()
        self._started = False
