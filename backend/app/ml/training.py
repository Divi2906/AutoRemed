
"""Generate isolated, verifier-labelled remediation experiments.

All experiments use temporary SQLite databases and SimulationExecutor.
The live application database and real host are never modified.
"""
from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from typing import Any

from app.container import Container
from app.remediation.executors import ExecutionRequest
from app.remediation.strategies import CATALOG
from app.settings import Settings
from app.core.util import ENV_SIM


FEATURES = [
    "incident_type",
    "severity",
    "metric",
    "value",
    "warning_threshold",
    "critical_threshold",
    "strategy_power",
    "strategy_kind",
]

START_VALUES = {
    "cpu": [76.0, 82.0, 91.0, 96.0, 99.0],
    "memory": [81.0, 85.0, 91.0, 96.0, 99.0],
    "disk": [86.0, 90.0, 96.0, 98.0, 99.0],
}


def generate_training_data(output_path: str) -> int:
    """Run every strategy against controlled starting states.

    Returns the number of experiment records written.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="autoremed_ml_") as tmp:
        settings = Settings(
            db_path=str(Path(tmp) / "training.db"),
            autostart_monitoring=False,
            step_delay_seconds=0,
            sync_dispatch=True,
        )
        container = Container(settings)

        try:
            for metric, incident_type in (
                ("cpu", "high_cpu"),
                ("memory", "high_memory"),
                ("disk", "high_disk"),
                ("service", "service_failure"),
            ):
                strategies = CATALOG[incident_type]

                if metric == "service":
                    scenarios = ["degraded", "failed"]
                    warning = None
                    critical = None
                else:
                    thresholds = container.config.thresholds()[metric]
                    warning = thresholds["warning"]
                    critical = thresholds["critical"]
                    scenarios = START_VALUES[metric]

                for start_value in scenarios:
                    for strategy in strategies:
                        # Every candidate starts from a clean, independent state.
                        container.sim.reset()

                        if metric == "service":
                            container.sim.inject_fault("service", start_value)
                            value = start_value
                        else:
                            container.sim.inject_fault(metric, start_value)
                            value = float(start_value)

                        before = container.verifier.capture()
                        epoch = before.get("epoch", container.sim.epoch)

                        request = ExecutionRequest(
                            incident_id="ML-EXPERIMENT",
                            attempt=1,
                            strategy=strategy,
                            environment=ENV_SIM,
                            metric=metric,
                            warning_threshold=warning,
                            epoch=epoch,
                        )

                        result = container.executors.get("simulation").execute(request)

                        incident = {
                            "id": "ML-EXPERIMENT",
                            "environment": ENV_SIM,
                            "metric": metric,
                        }

                        # Independent verification; never trust executor status as the label.
                        after = container.verifier.capture()
                        recovered, _ = container.verifier.evaluate(incident, after)

                        rows.append({
                            "incident_type": incident_type,
                            "severity": (
                                "critical" if metric == "service" or value >= critical
                                else "warning"
                            ),
                            "metric": metric,
                            "value": value,
                            "warning_threshold": warning,
                            "critical_threshold": critical,
                            "strategy": strategy.name,
                            "strategy_power": strategy.power,
                            "strategy_kind": strategy.kind,
                            "execution_status": result.status,
                            "verified_recovered": int(recovered),
                        })
        finally:
            container.shutdown()

    if not rows:
        raise RuntimeError("No training experiments were generated")

    fieldnames = list(rows[0].keys())
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)
