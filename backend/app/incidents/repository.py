"""Persistence for incidents, remediations, approvals, decisions, executions, verifications."""
from __future__ import annotations

from typing import Any

from ..core.db import Database
from ..core.errors import InvalidTransition, NotFound
from ..core.util import dumps, loads, utcnow

ACTIVE_WORKING = ("remediating", "retry_in_progress")
TERMINAL = ("resolved", "escalated", "rejected", "cancelled")

# Status transition table. 'escalated' and 'rejected' stay open (is_active=1) until the
# underlying condition clears or an operator closes them; their *status* never changes again.
ALLOWED: dict[str, set[str]] = {
    "detected": {"investigating", "pending_approval", "remediating", "resolved", "escalated", "cancelled"},
    "investigating": {"pending_approval", "remediating", "resolved", "escalated", "cancelled"},
    "pending_approval": {"approved", "rejected", "resolved", "cancelled"},
    "approved": {"remediating", "resolved", "escalated", "cancelled"},
    "remediating": {"retry_in_progress", "resolved", "escalated", "cancelled"},
    "retry_in_progress": {"remediating", "retry_in_progress", "resolved", "escalated", "cancelled"},
    "rejected": set(),
    "resolved": set(),
    "escalated": set(),
    "cancelled": set(),
}

_INCIDENT_JSON = {"diagnosis_json": "diagnosis", "scenario_json": "scenario", "final_state_json": "final_state"}
_INCIDENT_BOOL = ("is_active", "observe_only", "manual_intervention_required")


def _convert(row: dict[str, Any] | None, json_map: dict[str, str], bools: tuple[str, ...] = ()):
    if row is None:
        return None
    d = dict(row)
    for src, dst in json_map.items():
        if src in d:
            d[dst] = loads(d.pop(src))
    for b in bools:
        if b in d:
            d[b] = bool(d[b])
    return d


class Repositories:
    def __init__(self, db: Database):
        self.db = db

    # ================================================================== incidents
    def incident(self, incident_id: str) -> dict[str, Any] | None:
        return _convert(self.db.query_one("SELECT * FROM incidents WHERE id = ?", (incident_id,)),
                        _INCIDENT_JSON, _INCIDENT_BOOL)

    def require_incident(self, incident_id: str) -> dict[str, Any]:
        inc = self.incident(incident_id)
        if inc is None:
            raise NotFound(f"incident '{incident_id}' not found")
        return inc

    def active_incident_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        return _convert(
            self.db.query_one("SELECT * FROM incidents WHERE fingerprint = ? AND is_active = 1", (fingerprint,)),
            _INCIDENT_JSON, _INCIDENT_BOOL)

    def active_incidents(self, environment: str | None = None) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM incidents WHERE is_active = 1", []
        if environment:
            sql += " AND environment = ?"
            params.append(environment)
        rows = self.db.query(sql + " ORDER BY created_at DESC", params)
        return [_convert(r, _INCIDENT_JSON, _INCIDENT_BOOL) for r in rows]

    def list_incidents(
        self, *, status=None, severity=None, environment=None, type_=None, search=None,
        active_only=False, manual_only=False, sort="created_at", order="desc", limit=100, offset=0,
    ) -> tuple[list[dict[str, Any]], int]:
        where, params = ["1=1"], []
        for col, val in (("status", status), ("severity", severity), ("environment", environment), ("type", type_)):
            if val:
                where.append(f"{col} = ?")
                params.append(val)
        if active_only:
            where.append("is_active = 1")
        if manual_only:
            where.append("manual_intervention_required = 1")
        if search:
            where.append("(id LIKE ? OR description LIKE ? OR root_cause LIKE ? OR type LIKE ? OR metric LIKE ?)")
            params += [f"%{search}%"] * 5
        sortable = {"created_at", "severity", "status", "type", "environment", "value", "updated_at"}
        col = sort if sort in sortable else "created_at"
        direction = "ASC" if order.lower() == "asc" else "DESC"
        clause = " AND ".join(where)
        total = self.db.query_one(f"SELECT COUNT(*) AS n FROM incidents WHERE {clause}", params)["n"]
        rows = self.db.query(
            f"SELECT * FROM incidents WHERE {clause} ORDER BY {col} {direction}, created_at DESC LIMIT ? OFFSET ?",
            [*params, limit, offset])
        return [_convert(r, _INCIDENT_JSON, _INCIDENT_BOOL) for r in rows], total

    def transition(self, conn, incident_id: str, new_status: str, **fields: Any) -> None:
        """Validated status change (must be called inside a transaction)."""
        cur = conn.execute("SELECT status FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if cur is None:
            raise NotFound(f"incident '{incident_id}' not found")
        old = cur["status"]
        if new_status != old and new_status not in ALLOWED.get(old, set()):
            raise InvalidTransition(f"invalid incident transition {old} -> {new_status}")
        sets, params = ["status = ?", "updated_at = ?"], [new_status, utcnow()]
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            params.append(dumps(v) if k.endswith("_json") and not isinstance(v, str) else v)
        params.append(incident_id)
        conn.execute(f"UPDATE incidents SET {', '.join(sets)} WHERE id = ?", params)

    def counts(self) -> dict[str, Any]:
        q = self.db.query_one
        c = {
            "active": q("SELECT COUNT(*) n FROM incidents WHERE is_active=1")["n"],
            "active_critical": q("SELECT COUNT(*) n FROM incidents WHERE is_active=1 AND severity='critical'")["n"],
            "resolved": q("SELECT COUNT(*) n FROM incidents WHERE status='resolved'")["n"],
            "escalated": q("SELECT COUNT(*) n FROM incidents WHERE status='escalated'")["n"],
            "pending_approvals": q("SELECT COUNT(*) n FROM remediations WHERE approval_state='pending'")["n"],
            "manual_intervention": q(
                "SELECT COUNT(*) n FROM incidents WHERE is_active=1 AND manual_intervention_required=1")["n"],
            "total": q("SELECT COUNT(*) n FROM incidents")["n"],
            "remediated": q("SELECT COUNT(*) n FROM incidents WHERE resolution_type='remediated'")["n"],
        }
        denom = c["remediated"] + c["escalated"]
        c["remediation_success_rate"] = round(100.0 * c["remediated"] / denom, 1) if denom else None
        return c

    # ================================================================== remediations
    def remediation(self, remediation_id: str) -> dict[str, Any] | None:
        return _convert(self.db.query_one("SELECT * FROM remediations WHERE id = ?", (remediation_id,)),
                        {"proposal_json": "proposal"})

    def remediation_for_incident(self, incident_id: str) -> dict[str, Any] | None:
        return _convert(self.db.query_one("SELECT * FROM remediations WHERE incident_id = ?", (incident_id,)),
                        {"proposal_json": "proposal"})

    def list_remediations(self, *, status=None, approval_state=None, limit=100, offset=0):
        where, params = ["1=1"], []
        if status:
            where.append("r.status = ?")
            params.append(status)
        if approval_state:
            where.append("r.approval_state = ?")
            params.append(approval_state)
        clause = " AND ".join(where)
        total = self.db.query_one(f"SELECT COUNT(*) n FROM remediations r WHERE {clause}", params)["n"]
        rows = self.db.query(
            "SELECT r.*, i.type AS incident_type, i.severity, i.environment, i.metric, i.status AS incident_status,"
            " i.attempts_made, i.max_attempts, i.manual_intervention_required, i.is_active"
            f" FROM remediations r JOIN incidents i ON i.id = r.incident_id WHERE {clause}"
            " ORDER BY r.created_at DESC LIMIT ? OFFSET ?", [*params, limit, offset])
        out = []
        for r in rows:
            d = _convert(r, {"proposal_json": "proposal"}, ("manual_intervention_required", "is_active"))
            out.append(d)
        return out, total

    # ================================================================== approvals
    def approvals(self, incident_id: str | None = None, remediation_id: str | None = None) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM approvals WHERE 1=1", []
        if incident_id:
            sql += " AND incident_id = ?"
            params.append(incident_id)
        if remediation_id:
            sql += " AND remediation_id = ?"
            params.append(remediation_id)
        return self.db.query(sql + " ORDER BY created_at ASC", params)

    # ================================================================== decisions
    _DECISION_JSON = {"context_json": "context", "previous_outcomes_json": "previous_outcomes",
                      "alternatives_json": "alternatives"}

    def decisions(self, incident_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM strategy_decisions WHERE incident_id = ? ORDER BY attempt", (incident_id,))
        return [_convert(r, self._DECISION_JSON) for r in rows]

    def decision(self, incident_id: str, attempt: int) -> dict[str, Any] | None:
        return _convert(self.db.query_one(
            "SELECT * FROM strategy_decisions WHERE incident_id = ? AND attempt = ?", (incident_id, attempt)),
            self._DECISION_JSON)

    # ================================================================== executions
    def executions(self, incident_id: str | None = None, *, limit=200, offset=0, status=None):
        where, params = ["1=1"], []
        if incident_id:
            where.append("incident_id = ?")
            params.append(incident_id)
        if status:
            where.append("status = ?")
            params.append(status)
        clause = " AND ".join(where)
        total = self.db.query_one(f"SELECT COUNT(*) n FROM executions WHERE {clause}", params)["n"]
        rows = self.db.query(
            f"SELECT * FROM executions WHERE {clause} ORDER BY started_at DESC, attempt DESC LIMIT ? OFFSET ?",
            [*params, limit, offset])
        return rows, total

    def execution(self, execution_id: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM executions WHERE id = ?", (execution_id,))

    # ================================================================== verifications
    _VER_JSON = {"before_json": "before", "after_json": "after", "criteria_json": "criteria"}

    def verifications(self, incident_id: str | None = None, *, limit=200, offset=0):
        where, params = ["1=1"], []
        if incident_id:
            where.append("incident_id = ?")
            params.append(incident_id)
        clause = " AND ".join(where)
        total = self.db.query_one(f"SELECT COUNT(*) n FROM verifications WHERE {clause}", params)["n"]
        rows = self.db.query(
            f"SELECT * FROM verifications WHERE {clause} ORDER BY created_at DESC, attempt DESC LIMIT ? OFFSET ?",
            [*params, limit, offset])
        return [_convert(r, self._VER_JSON) for r in rows], total

    def verification(self, verification_id: str) -> dict[str, Any] | None:
        return _convert(self.db.query_one("SELECT * FROM verifications WHERE id = ?", (verification_id,)),
                        self._VER_JSON)

    # ================================================================== attempt timeline
    def attempts(self, incident_id: str) -> list[dict[str, Any]]:
        """Merge decision + execution + verification per attempt number."""
        decisions = {d["attempt"]: d for d in self.decisions(incident_id)}
        execs = {e["attempt"]: e for e in self.db.query(
            "SELECT * FROM executions WHERE incident_id = ? ORDER BY attempt", (incident_id,))}
        vers = {v["attempt"]: v for v in self.verifications(incident_id)[0]}
        out = []
        for n in sorted(set(decisions) | set(execs) | set(vers)):
            d, e, v = decisions.get(n), execs.get(n), vers.get(n)
            if e is None:
                outcome = "planned"
            elif e["status"] == "running":
                outcome = "in_progress"
            elif v is not None and v["result"] == "recovered":
                outcome = "recovered_verified"
            elif e["status"] == "failed":
                outcome = "execution_failed"
            else:
                outcome = "execution_succeeded_issue_remains"
            failure = None
            if outcome == "execution_failed":
                failure = e.get("error") or e.get("message")
            elif outcome == "execution_succeeded_issue_remains" and v:
                failure = v.get("failure_reason")
            out.append({
                "attempt": n,
                "strategy": (e or d or {}).get("strategy"),
                "outcome": outcome,
                "decision": d,
                "execution": e,
                "verification": v,
                "state_before": v["before"] if v else None,
                "state_after": v["after"] if v else None,
                "failure_reason": failure,
                "started_at": e["started_at"] if e else (d["created_at"] if d else None),
                "duration_ms": e["duration_ms"] if e else None,
                "message": e["message"] if e else None,
            })
        return out

    # ================================================================== demo runs
    def demo_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM demo_runs ORDER BY ts DESC LIMIT ?", (limit,))
        return [_convert(r, {"params_json": "params"}) for r in rows]
