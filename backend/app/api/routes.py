"""REST API (mounted under /api). Thin layer: validation + serialization over the services."""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request

from ..container import Container
from ..core.errors import Conflict, NotFound
from ..core.util import ENV_LABELS, ENV_REAL, ENV_SIM, utcnow
from ..monitoring.health import overall
from . import schemas as S

VERSION = "1.0.0"
router = APIRouter()


def get_container(request: Request) -> Container:
    return request.app.state.container


C = Depends(get_container)


def _inc(d: dict[str, Any]) -> dict[str, Any]:
    return {**d, "environment_label": ENV_LABELS[d["environment"]]}


def _env_metrics(m: dict[str, Any]) -> dict[str, Any]:
    return {**m, "label": ENV_LABELS[m["environment"]]}


# ====================================================================== health / metrics / monitoring
@router.get("/health", response_model=S.HealthOut, tags=["system"], summary="Application health")
def health(c: Container = C):
    c.db.query_one("SELECT 1 AS ok")
    return {"status": "ok", "database": "ok", "monitoring_running": c.monitor.running, "mode": c.config.mode(),
            "version": VERSION, "time": utcnow()}


@router.get("/metrics/current", response_model=S.CurrentMetrics, tags=["monitoring"],
            summary="Current metrics for REAL HOST and SIMULATION (kept separate)")
def metrics_current(c: Container = C):
    cur = c.monitor.current()
    return {"real_host": _env_metrics(cur[ENV_REAL]), "simulation": _env_metrics(cur[ENV_SIM]),
            "thresholds": c.config.thresholds(), "monitoring": c.monitor.status(), "mode": c.config.mode()}


@router.get("/metrics/history", response_model=list[S.MetricPoint], tags=["monitoring"],
            summary="Persisted metric history for one environment (oldest first)")
def metrics_history(environment: S.Environment = Query(...), limit: int = Query(120, ge=1, le=2000),
                    c: Container = C):
    return c.monitor.history(environment, limit)


@router.get("/monitoring/status", response_model=S.MonitoringStatus, tags=["monitoring"])
def monitoring_status(c: Container = C):
    return c.monitor.status()


@router.post("/monitoring/start", response_model=S.MonitoringAction, tags=["monitoring"])
def monitoring_start(body: Optional[S.MonitoringStart] = None, c: Container = C):
    changed = c.monitor.start(body.interval_seconds if body else None)
    return {"changed": changed, "status": c.monitor.status()}


@router.post("/monitoring/stop", response_model=S.MonitoringAction, tags=["monitoring"])
def monitoring_stop(c: Container = C):
    changed = c.monitor.stop()
    return {"changed": changed, "status": c.monitor.status()}


@router.get("/summary", response_model=S.SummaryOut, tags=["dashboard"], summary="Dashboard KPIs")
def summary(c: Container = C):
    cur = c.monitor.current()
    counts = c.repos.counts()
    return {**counts, "real_host_health": cur[ENV_REAL]["health"], "simulation_health": cur[ENV_SIM]["health"],
            "mode": c.config.mode()}


# ====================================================================== incidents
@router.get("/incidents", response_model=S.Page[S.IncidentOut], tags=["incidents"])
def incidents_list(
    status: Optional[str] = None, severity: Optional[Literal["warning", "critical"]] = None,
    environment: Optional[S.Environment] = None, type: Optional[str] = None, q: Optional[str] = None,
    active_only: bool = False, manual_only: bool = False,
    sort: str = "created_at", order: Literal["asc", "desc"] = "desc",
    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), c: Container = C,
):
    items, total = c.repos.list_incidents(
        status=status, severity=severity, environment=environment, type_=type, search=q, active_only=active_only,
        manual_only=manual_only, sort=sort, order=order, limit=limit, offset=offset)
    return {"items": [_inc(i) for i in items], "total": total, "limit": limit, "offset": offset}


@router.get("/incidents/active", response_model=list[S.IncidentOut], tags=["incidents"])
def incidents_active(environment: Optional[S.Environment] = None, c: Container = C):
    return [_inc(i) for i in c.repos.active_incidents(environment)]


@router.post("/incidents/simulate", response_model=S.SimulateOut, status_code=201, tags=["incidents"],
             summary="Inject a fault into the SIMULATION (goes through the real detection pipeline)")
def incidents_simulate(body: S.SimulateRequest, c: Container = C):
    return c.demo.inject(body.fault, value=body.value, plan=body.plan, mode_override=body.mode_override,
                         source="api")


@router.get("/incidents/{incident_id}", response_model=S.IncidentDetail, tags=["incidents"])
def incident_detail(incident_id: str, c: Container = C):
    inc = c.repos.require_incident(incident_id)
    timeline, _ = c.activity.query(incident_id=incident_id, limit=500, newest_first=False)
    current = None
    if inc["environment"] == ENV_SIM:
        s = c.sim.snapshot()
        current = s["service_state"] if inc["metric"] == "service" else f"{s[inc['metric']]:.1f}%"
    else:
        row = c.monitor.history(ENV_REAL, 1)
        if row and row[0].get(inc["metric"]) is not None:
            current = f"{row[0][inc['metric']]:.1f}%"
    return {"incident": _inc(inc), "remediation": c.repos.remediation_for_incident(incident_id),
            "attempts": c.repos.attempts(incident_id), "decisions": c.repos.decisions(incident_id),
            "approvals": c.repos.approvals(incident_id=incident_id),
            "timeline": timeline, "current_value": current}


@router.post("/incidents/{incident_id}/resolve", response_model=S.IncidentOut, tags=["incidents"],
             summary="Operator closes an escalated/rejected incident once the condition is actually healthy")
def incident_resolve(incident_id: str, body: Optional[S.ResolveRequest] = None, c: Container = C):
    inc = c.repos.require_incident(incident_id)
    if not inc["is_active"]:
        raise Conflict("incident is already closed")
    if inc["status"] not in ("escalated", "rejected"):
        raise Conflict(f"only escalated or rejected incidents can be closed manually (status: {inc['status']})")
    if inc["environment"] == ENV_SIM:
        healthy = c.verifier.is_healthy(inc)
    else:
        cur = c.monitor.current()[ENV_REAL]
        healthy = cur["statuses"].get(inc["metric"]) == "ok"
    if not healthy:
        raise Conflict("the underlying condition is still unhealthy; fix it (or reset the demo) before closing")
    c.db.execute("UPDATE incidents SET is_active=0, closed_reason='manually_closed', updated_at=? WHERE id=?",
                 (utcnow(), incident_id))
    c.activity.log("incident_closed", "Incident closed manually by operator"
                   + (f": {body.note}" if body and body.note else ""), incident_id=incident_id, action="close",
                   status=inc["status"], environment=inc["environment"])
    return _inc(c.repos.require_incident(incident_id))


# ====================================================================== remediation / approvals
@router.get("/remediation", response_model=S.Page[S.RemediationOut], tags=["remediation"])
def remediation_list(status: Optional[str] = None, approval_state: Optional[str] = None,
                     limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), c: Container = C):
    items, total = c.repos.list_remediations(status=status, approval_state=approval_state, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def _remediation_detail(c: Container, rem: dict[str, Any]) -> dict[str, Any]:
    inc = c.repos.require_incident(rem["incident_id"])
    return {**rem, "incident": _inc(inc), "attempts": c.repos.attempts(inc["id"]),
            "approvals": c.repos.approvals(remediation_id=rem["id"])}


@router.get("/remediation/{remediation_id}", response_model=S.RemediationDetail, tags=["remediation"])
def remediation_detail(remediation_id: str, c: Container = C):
    rem = c.repos.remediation(remediation_id)
    if rem is None:
        raise NotFound(f"remediation '{remediation_id}' not found")
    return _remediation_detail(c, rem)


@router.post("/remediation/{remediation_id}/approve", response_model=S.RemediationDetail, tags=["remediation"],
             summary="Approve a pending remediation (starts the normal execute/verify/retry workflow)")
def remediation_approve(remediation_id: str, body: Optional[S.DecisionRequest] = None, c: Container = C):
    b = body or S.DecisionRequest()
    c.orchestrator.approve(remediation_id, b.actor, b.note)
    return _remediation_detail(c, c.repos.remediation(remediation_id))


@router.post("/remediation/{remediation_id}/reject", response_model=S.RemediationDetail, tags=["remediation"],
             summary="Reject a pending remediation (it will never execute)")
def remediation_reject(remediation_id: str, body: Optional[S.DecisionRequest] = None, c: Container = C):
    b = body or S.DecisionRequest()
    c.orchestrator.reject(remediation_id, b.actor, b.note)
    return _remediation_detail(c, c.repos.remediation(remediation_id))


# ====================================================================== executions / verification / logs
@router.get("/executions", response_model=S.Page[S.ExecutionOut], tags=["executions"])
def executions_list(incident_id: Optional[str] = None, status: Optional[str] = None,
                    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), c: Container = C):
    items, total = c.repos.executions(incident_id, limit=limit, offset=offset, status=status)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/executions/{execution_id}", response_model=S.ExecutionOut, tags=["executions"])
def execution_detail(execution_id: str, c: Container = C):
    ex = c.repos.execution(execution_id)
    if ex is None:
        raise NotFound(f"execution '{execution_id}' not found")
    return ex


@router.get("/verification", response_model=S.Page[S.VerificationOut], tags=["verification"])
def verification_list(incident_id: Optional[str] = None, limit: int = Query(100, ge=1, le=500),
                      offset: int = Query(0, ge=0), c: Container = C):
    items, total = c.repos.verifications(incident_id, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/verification/{verification_id}", response_model=S.VerificationOut, tags=["verification"])
def verification_detail(verification_id: str, c: Container = C):
    v = c.repos.verification(verification_id)
    if v is None:
        raise NotFound(f"verification '{verification_id}' not found")
    return v


@router.get("/activity-logs", response_model=S.Page[S.ActivityOut], tags=["activity"])
def activity_logs(event_type: Optional[str] = None, incident_id: Optional[str] = None, status: Optional[str] = None,
                  environment: Optional[S.Environment] = None, q: Optional[str] = None,
                  limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), c: Container = C):
    items, total = c.activity.query(event_type=event_type, incident_id=incident_id, status=status,
                                    environment=environment, search=q, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# ====================================================================== config
def _config(c: Container) -> dict[str, Any]:
    r = c.selector.ranker
    return {
        "thresholds": c.config.thresholds(), "mode": c.config.mode(), "monitoring": c.config.monitoring(),
        "consecutive_violations": {e: c.config.consecutive_required(e) for e in (ENV_REAL, ENV_SIM)},
        "ranker": r.kind,
        "ranker_info": {"kind": r.kind, "trained_model": r.trained,
                        "note": c.selector.note or "Deterministic rule-based ranking. No ML model is trained or used."},
        "max_attempts": 3, "executors": c.executors.names(),
    }


@router.get("/config", response_model=S.ConfigOut, tags=["config"])
def config_get(c: Container = C):
    return _config(c)


@router.put("/config/thresholds", response_model=S.ConfigOut, tags=["config"])
def config_thresholds(body: S.ThresholdUpdate, c: Container = C):
    c.config.set_thresholds({k: getattr(body, k).model_dump(exclude_none=True)
                             for k in ("cpu", "memory", "disk") if getattr(body, k) is not None})
    return _config(c)


@router.put("/config/mode", response_model=S.ConfigOut, tags=["config"],
            summary="Switch between Autonomous and Approval mode (applies to newly detected incidents)")
def config_mode(body: S.ModeUpdate, c: Container = C):
    c.config.set_mode(body.mode)
    return _config(c)


@router.put("/config/monitoring", response_model=S.ConfigOut, tags=["config"])
def config_monitoring(body: S.MonitoringUpdate, c: Container = C):
    if body.interval_seconds is not None:
        c.config.set_monitoring(interval_seconds=body.interval_seconds)
    if body.consecutive_violations_real_host is not None:
        c.config.set_consecutive(ENV_REAL, body.consecutive_violations_real_host)
    if body.consecutive_violations_simulation is not None:
        c.config.set_consecutive(ENV_SIM, body.consecutive_violations_simulation)
    return _config(c)


# ====================================================================== demo
@router.get("/demo/scenarios", response_model=S.ScenarioList, tags=["demo"])
def demo_scenarios(c: Container = C):
    return c.demo.scenarios()


@router.post("/demo/scenario", response_model=S.ScenarioTriggerOut, status_code=201, tags=["demo"],
             summary="Run a deterministic scenario through the real pipeline (SIMULATION only)")
def demo_scenario(body: S.ScenarioRequest, c: Container = C):
    return c.demo.trigger(body.scenario, body.fault)


@router.post("/demo/recover", response_model=S.RecoverOut, tags=["demo"])
def demo_recover(body: S.RecoverRequest, c: Container = C):
    return c.demo.recover(body.fault)


@router.post("/demo/reset", response_model=S.ResetOut, tags=["demo"],
             summary="Reset simulated state; closes active simulation incidents but keeps all history")
def demo_reset(c: Container = C):
    return c.demo.reset()


@router.get("/demo/history", response_model=list[S.DemoRun], tags=["demo"])
def demo_history(limit: int = Query(50, ge=1, le=200), c: Container = C):
    return c.demo.history(limit)
