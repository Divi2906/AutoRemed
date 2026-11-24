"""Deterministic, explainable diagnosis rules (no ML, no external services)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..core.util import ENV_LABELS, ENV_REAL

TYPE_BY_METRIC = {"cpu": "high_cpu", "memory": "high_memory", "disk": "high_disk", "service": "service_failure"}
METRIC_BY_TYPE = {v: k for k, v in TYPE_BY_METRIC.items()}

_LABEL = {"cpu": "CPU utilisation", "memory": "Memory utilisation", "disk": "Disk utilisation",
          "service": "Service state"}

_RULES: dict[str, dict[str, str]] = {
    "high_cpu": {
        "cause": "Sustained compute load - a runaway or CPU-bound process, or a workload spike exceeding capacity.",
        "manual": "Identify the top CPU consumers (top/Task Manager), throttle or restart the offending "
                  "workload, and check for runaway loops or recent deployments; scale out if load is legitimate.",
    },
    "high_memory": {
        "cause": "Memory pressure - likely a leak, an oversized cache, or too many concurrent workloads.",
        "manual": "Find the largest memory consumers, restart leaking services, review cache sizing, and "
                  "consider adding memory or limiting concurrency.",
    },
    "high_disk": {
        "cause": "Storage exhaustion - log/temp/cache growth or a large unexpected file set on the volume.",
        "manual": "Locate the largest directories, rotate or archive logs, clear temp/cache data under change "
                  "control, and expand the volume if growth is expected.",
    },
    "service_failure": {
        "cause": "A monitored service is not running healthily - crash, failed dependency or bad configuration.",
        "manual": "Inspect the service logs and its dependencies, fix the underlying fault, and restart the "
                  "service through your normal change process.",
    },
}


@dataclass
class Diagnosis:
    rule_id: str
    summary: str
    probable_root_cause: str
    evidence: list[str] = field(default_factory=list)
    recommended_manual_step: str = ""
    method: str = "rule_based"  # never "ml": these are fixed, explainable rules

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DiagnosisEngine:
    def diagnose(
        self,
        *,
        incident_type: str,
        severity: str,
        environment: str,
        metric: str,
        value_label: str,
        threshold_label: str,
        snapshot: dict[str, Any],
        statuses: dict[str, str],
        thresholds: dict[str, dict[str, float]],
    ) -> Diagnosis:
        rule = _RULES[incident_type]
        env = ENV_LABELS[environment]
        evidence = [
            f"{_LABEL[metric]} is {value_label} in {env}, "
            f"{'at or above the critical' if severity == 'critical' else 'at or above the warning'} "
            f"threshold of {threshold_label}.",
        ]
        correlated = [m for m in ("cpu", "memory", "disk") if m != metric and statuses.get(m) in ("warning", "critical")]
        for m in correlated:
            evidence.append(f"{_LABEL[m]} is also elevated ({snapshot.get(m)}%) - possible correlated pressure.")
        if incident_type == "high_cpu" and "memory" in correlated:
            evidence.append("High memory alongside high CPU can indicate swapping or garbage-collection thrash.")
        if incident_type == "service_failure":
            evidence = [f"Service state is '{snapshot.get('service_state')}' (expected 'running') in {env}."]
            if correlated:
                evidence.append("Resource metrics are also elevated, so resource exhaustion may have caused the failure.")
        manual = rule["manual"]
        if environment == ENV_REAL:
            manual = ("AutoRemed monitors the real host read-only and never remediates it. " + manual)
        return Diagnosis(
            rule_id=f"{incident_type}.{severity}",
            summary=f"{_LABEL[metric]} {severity} in {env}: {value_label} (threshold {threshold_label}).",
            probable_root_cause=rule["cause"],
            evidence=evidence,
            recommended_manual_step=manual,
        )
