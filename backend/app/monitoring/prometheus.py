from __future__ import annotations

from prometheus_client import CollectorRegistry, Gauge, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST


class PrometheusExporter:
    """Expose read-only AutoRemed application and incident metrics."""

    def __init__(self, container):
        self.container = container
        self.registry = CollectorRegistry()

        self.monitoring_running = Gauge(
            "autoremed_monitoring_running",
            "Whether AutoRemed monitoring is running (1=yes, 0=no)",
            registry=self.registry,
        )

        self.monitoring_ticks = Gauge(
            "autoremed_monitoring_ticks",
            "Number of monitoring ticks completed by this process",
            registry=self.registry,
        )

        self.monitoring_errors = Gauge(
            "autoremed_monitoring_errors",
            "Number of monitoring errors recorded by this process",
            registry=self.registry,
        )

        self.incidents = {
            name: Gauge(
                f"autoremed_incidents_{name}",
                f"Current database count of {name.replace('_', ' ')} incidents",
                registry=self.registry,
            )
            for name in (
                "active",
                "active_critical",
                "resolved",
                "escalated",
                "pending_approvals",
                "manual_intervention",
                "total",
                "remediated",
            )
        }

        self.remediation_success_rate = Gauge(
            "autoremed_remediation_success_rate",
            "Remediation success rate as a percentage; -1 means unavailable",
            registry=self.registry,
        )

    def render(self) -> bytes:
        """Refresh metrics from existing read-only application state."""

        monitor = self.container.monitor
        status = monitor.status()

        self.monitoring_running.set(1 if status["running"] else 0)
        self.monitoring_ticks.set(status["tick_count"])
        self.monitoring_errors.set(status["error_count"])

        counts = self.container.repos.counts()

        for name, metric in self.incidents.items():
            metric.set(counts[name])

        success_rate = counts["remediation_success_rate"]
        self.remediation_success_rate.set(-1 if success_rate is None else success_rate)

        return generate_latest(self.registry)

    @property
    def content_type(self) -> str:
        return CONTENT_TYPE_LATEST
