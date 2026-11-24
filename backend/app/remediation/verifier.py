"""Independent health verification.

The verifier never looks at what the executor reported. It re-reads the simulated state itself
and compares it with explicit recovery criteria (metric back below its warning threshold, or
service back to 'running').
"""
from __future__ import annotations

from typing import Any, Callable

from ..core.activity import ActivityLog
from ..core.config_service import ConfigService
from ..core.db import Database
from ..core.errors import SafetyViolation
from ..core.util import ENV_SIM, dumps, new_id, utcnow


class HealthVerifier:
    def __init__(self, db: Database, config: ConfigService, activity: ActivityLog,
                 read_state: Callable[[], dict[str, Any]]):
        self.db, self.config, self.activity = db, config, activity
        self._read_state = read_state  # independent read of the simulated state

    def capture(self) -> dict[str, Any]:
        s = self._read_state()
        return {"cpu": s["cpu"], "memory": s["memory"], "disk": s["disk"], "service_state": s["service_state"]}

    def criteria(self, incident: dict[str, Any]) -> dict[str, Any]:
        if incident["metric"] == "service":
            return {"metric": "service", "expected": "running", "rule": "service_state == 'running'"}
        warn = self.config.thresholds()[incident["metric"]]["warning"]
        return {"metric": incident["metric"], "healthy_below": warn,
                "rule": f"{incident['metric']} < {warn:.1f}% (below the warning threshold)"}

    def evaluate(self, incident: dict[str, Any], state: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:
        if incident["environment"] != ENV_SIM:
            raise SafetyViolation("verification/remediation is only supported for the simulation environment")
        state = state or self.capture()
        crit = self.criteria(incident)
        if incident["metric"] == "service":
            return state["service_state"] == "running", crit
        return state[incident["metric"]] < crit["healthy_below"], crit

    def is_healthy(self, incident: dict[str, Any]) -> bool:
        return self.evaluate(incident)[0]

    def verify(self, incident: dict[str, Any], attempt: int, execution_id: str | None,
               before: dict[str, Any]) -> dict[str, Any]:
        after = self.capture()
        recovered, crit = self.evaluate(incident, after)
        reason = None
        if not recovered:
            m = incident["metric"]
            if m == "service":
                reason = f"service is still '{after['service_state']}' (expected 'running')"
                if after["service_state"] == before["service_state"]:
                    reason += "; state unchanged by the action"
            else:
                b, a = before[m], after[m]
                if a == b:
                    reason = f"{m} unchanged at {a:.1f}% (still >= {crit['healthy_below']:.1f}%)"
                elif a < b:
                    reason = (f"{m} improved {b:.1f}% -> {a:.1f}% but is still >= "
                              f"{crit['healthy_below']:.1f}% (not recovered)")
                else:
                    reason = f"{m} worsened {b:.1f}% -> {a:.1f}% (still >= {crit['healthy_below']:.1f}%)"
        vid = new_id("VER")
        result = "recovered" if recovered else "not_recovered"
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO verifications (id, incident_id, execution_id, attempt, before_json, after_json,"
                " criteria_json, result, failure_reason, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (vid, incident["id"], execution_id, attempt, dumps(before), dumps(after), dumps(crit),
                 result, reason, utcnow()))
            self.activity.log(
                "verification",
                f"Independent verification {'CONFIRMED recovery' if recovered else 'did NOT confirm recovery'}"
                + (f": {reason}" if reason else ""),
                incident_id=incident["id"], action="verify", status=result, attempt=attempt,
                environment=incident["environment"], details={"before": before, "after": after, "criteria": crit})
        return {"id": vid, "result": result, "recovered": recovered, "failure_reason": reason,
                "before": before, "after": after, "criteria": crit}
