"""REST API contract tests (through FastAPI TestClient against the real container)."""
from __future__ import annotations

import pytest


def post_scn(client, scenario, fault="cpu"):
    r = client.post("/api/demo/scenario", json={"scenario": scenario, "fault": fault})
    assert r.status_code == 201, r.text
    return r.json()


def assert_error(r, status, code):
    assert r.status_code == status, r.text
    body = r.json()
    assert set(body) == {"error"} and body["error"]["code"] == code and body["error"]["message"]


def test_health(client):
    j = client.get("/api/health").json()
    assert j["status"] == "ok" and j["database"] == "ok" and j["mode"] == "autonomous"


def test_metrics_current_keeps_environments_separate_and_labelled(client, container):
    container.sim.inject_fault("cpu", 55)
    j = client.get("/api/metrics/current").json()
    assert j["real_host"]["label"] == "REAL HOST" and j["simulation"]["label"] == "SIMULATION"
    assert j["simulation"]["cpu"] == 55.0 and j["real_host"]["cpu"] != 55.0
    assert j["real_host"]["service_state"] is None and j["simulation"]["service_state"] == "running"


def test_metrics_history_and_validation(client, container):
    container.monitor.tick(); container.monitor.tick()
    for env in ("real_host", "simulation"):
        pts = client.get("/api/metrics/history", params={"environment": env, "limit": 10}).json()
        assert len(pts) >= 2 and {"ts", "cpu", "memory", "disk"} <= set(pts[0])
    assert client.get("/api/metrics/history").status_code == 422
    assert client.get("/api/metrics/history", params={"environment": "mars"}).status_code == 422


def test_monitoring_start_stop_no_duplicate_loops(client, container):
    try:
        assert client.post("/api/monitoring/start").status_code == 200
        client.post("/api/monitoring/start")
        client.post("/api/monitoring/start")
        st = client.get("/api/monitoring/status").json()
        assert st["running"] is True and st["thread_count"] == 1
        assert client.post("/api/monitoring/stop").status_code == 200
        st = client.get("/api/monitoring/status").json()
        assert st["running"] is False and st["thread_count"] == 0
    finally:
        container.monitor.shutdown()


def test_incident_endpoints(client):
    inc_id = post_scn(client, "all_attempts_fail", "disk")["incident_id"]
    page = client.get("/api/incidents").json()
    assert page["total"] == 1 and page["items"][0]["id"] == inc_id
    assert [i["id"] for i in client.get("/api/incidents/active").json()] == [inc_id]   # escalated stays active
    d = client.get(f"/api/incidents/{inc_id}").json()
    assert d["incident"]["status"] == "escalated" and d["incident"]["manual_intervention_required"] is True
    assert len(d["attempts"]) == 3 and len(d["decisions"]) == 3 and d["timeline"]
    assert_error(client.get("/api/incidents/NOPE"), 404, "not_found")


def test_incident_filters_search_sorting(client):
    post_scn(client, "first_attempt_succeeds", "cpu")
    post_scn(client, "all_attempts_fail", "memory")
    q = lambda **p: client.get("/api/incidents", params=p).json()          # noqa: E731
    assert q(status="resolved")["total"] == 1 and q(status="escalated")["total"] == 1
    assert q(metric="memory")["items"][0]["metric"] == "memory"
    assert q(search="memory")["total"] >= 1
    assert q(environment="real_host")["total"] == 0
    assert len(q(limit=1)["items"]) == 1
    assert client.get("/api/incidents", params={"limit": 0}).status_code == 422


def test_simulate_endpoint_runs_real_pipeline(client, container):
    r = client.post("/api/incidents/simulate", json={"fault": "memory", "plan": ["recover"]})
    assert r.status_code == 201
    inc = client.get(f"/api/incidents/{r.json()['incident_id']}").json()["incident"]
    assert inc["status"] == "resolved" and inc["attempts_made"] == 1
    again = client.post("/api/incidents/simulate", json={"fault": "memory", "plan": ["recover"]})
    assert again.status_code == 201                       # earlier incident closed -> new fault allowed


def test_simulate_validation_and_conflict(client, container):
    assert client.post("/api/incidents/simulate", json={"fault": "gpu"}).status_code == 422
    assert client.post("/api/incidents/simulate", json={"fault": "cpu", "plan": ["a", "b"]}).status_code == 422
    assert client.post("/api/incidents/simulate", json={"fault": "cpu", "bogus": 1}).status_code == 422
    assert client.post("/api/incidents/simulate", json={"fault": "cpu", "value": 400}).status_code == 422
    client.post("/api/incidents/simulate", json={"fault": "cpu", "plan": ["exec_fail"] * 3})
    assert_error(client.post("/api/incidents/simulate", json={"fault": "cpu"}), 409, "conflict")


def test_remediation_approval_flow_over_api(client):
    inc_id = post_scn(client, "approval_required", "cpu")["incident_id"]
    rems = client.get("/api/remediation", params={"approval_state": "pending"}).json()
    assert rems["total"] == 1
    rid = rems["items"][0]["id"]
    d = client.get(f"/api/remediation/{rid}").json()
    assert d["proposal"]["reason"] and d["approvals"][0]["action"] == "requested"
    assert client.get("/api/executions", params={"incident_id": inc_id}).json()["total"] == 0
    r = client.post(f"/api/remediation/{rid}/approve", json={"actor": "qa", "note": "ok"})
    assert r.status_code == 200 and r.json()["approval_state"] == "approved"
    assert client.get(f"/api/incidents/{inc_id}").json()["incident"]["status"] == "resolved"
    assert_error(client.post(f"/api/remediation/{rid}/approve"), 409, "conflict")
    assert_error(client.post(f"/api/remediation/{rid}/reject"), 409, "conflict")


def test_rejection_over_api_never_executes(client):
    inc_id = post_scn(client, "approval_required", "memory")["incident_id"]
    rid = client.get("/api/remediation", params={"approval_state": "pending"}).json()["items"][0]["id"]
    assert client.post(f"/api/remediation/{rid}/reject", json={"note": "no"}).status_code == 200
    assert client.get("/api/executions", params={"incident_id": inc_id}).json()["total"] == 0
    assert client.get(f"/api/incidents/{inc_id}").json()["incident"]["status"] == "rejected"
    assert_error(client.post("/api/remediation/REM-NOPE/approve"), 404, "not_found")


def test_executions_and_verification_endpoints(client):
    inc_id = post_scn(client, "second_attempt_succeeds", "cpu")["incident_id"]
    ex = client.get("/api/executions", params={"incident_id": inc_id}).json()
    assert ex["total"] == 2
    one = client.get(f"/api/executions/{ex['items'][0]['id']}").json()
    assert one["incident_id"] == inc_id and one["environment"] == "simulation"
    assert client.get("/api/executions", params={"status": "failed"}).json()["total"] == 1
    ver = client.get("/api/verification", params={"incident_id": inc_id}).json()
    assert ver["total"] >= 1
    assert client.get(f"/api/verification/{ver['items'][0]['id']}").json()["incident_id"] == inc_id
    assert_error(client.get("/api/executions/NOPE"), 404, "not_found")
    assert_error(client.get("/api/verification/NOPE"), 404, "not_found")


def test_activity_logs_and_filters(client):
    inc_id = post_scn(client, "all_attempts_fail", "cpu")["incident_id"]
    allp = client.get("/api/activity-logs", params={"limit": 500}).json()
    assert allp["total"] > 10
    for k in ("ts", "event_type", "incident_id", "action", "status", "attempt", "message"):
        assert k in allp["items"][0]
    esc = client.get("/api/activity-logs", params={"event_type": "incident_escalated"}).json()
    assert esc["total"] == 1 and esc["items"][0]["incident_id"] == inc_id
    assert client.get("/api/activity-logs", params={"incident_id": inc_id}).json()["total"] > 5
    ts = [i["ts"] for i in allp["items"]]
    assert ts == sorted(ts, reverse=True)


def test_config_thresholds(client):
    assert client.get("/api/config").json()["thresholds"]["cpu"] == {"warning": 75.0, "critical": 90.0}
    r = client.put("/api/config/thresholds", json={"cpu": {"warning": 60, "critical": 85}})
    assert r.status_code == 200 and r.json()["thresholds"]["cpu"] == {"warning": 60.0, "critical": 85.0}
    assert client.get("/api/config").json()["thresholds"]["memory"]["warning"] == 80.0   # untouched
    assert_error(client.put("/api/config/thresholds", json={"cpu": {"warning": 95, "critical": 80}}), 422, "validation_error")
    assert client.put("/api/config/thresholds", json={"cpu": {"warning": 500}}).status_code == 422
    assert client.put("/api/config/thresholds", json={"gpu": {"warning": 5}}).status_code == 422


def test_threshold_change_takes_effect_on_detection(client, container):
    client.put("/api/config/thresholds", json={"cpu": {"warning": 40, "critical": 50}})
    container.executors.register(__import__("app.remediation.executors", fromlist=["x"]).TestExecutor(["fail"] * 9))
    container.executors.default = "test"
    container.sim.inject_fault("cpu", 55)
    container.monitor.tick()
    inc = client.get("/api/incidents").json()["items"][0]
    assert inc["severity"] == "critical" and inc["threshold"] == 50.0


def test_mode_and_monitoring_config(client):
    assert client.put("/api/config/mode", json={"mode": "approval"}).json()["mode"] == "approval"
    assert client.get("/api/health").json()["mode"] == "approval"
    assert client.put("/api/config/mode", json={"mode": "yolo"}).status_code == 422
    r = client.put("/api/config/monitoring", json={"interval_seconds": 2})
    assert r.status_code == 200 and r.json()["monitoring"]["interval_seconds"] == 2.0
    assert client.put("/api/config/monitoring", json={"interval_seconds": 0}).status_code == 422


def test_summary_counts(client):
    post_scn(client, "first_attempt_succeeds", "cpu")
    post_scn(client, "all_attempts_fail", "memory")
    post_scn(client, "approval_required", "disk")
    s = client.get("/api/summary").json()
    assert s["resolved"] == 1 and s["escalated"] == 1 and s["pending_approvals"] == 1
    assert s["manual_intervention"] == 1 and s["total"] == 3 and s["active"] == 2
    assert s["remediation_success_rate"] == pytest.approx(0.5) or s["remediation_success_rate"] == pytest.approx(50.0)


def test_demo_endpoints(client, container):
    j = client.get("/api/demo/scenarios").json()
    assert len(j["scenarios"]) == 8 and len(j["faults"]) == 4
    post_scn(client, "first_attempt_succeeds", "cpu")
    assert len(client.get("/api/demo/history").json()) == 1
    assert_error(client.post("/api/demo/scenario", json={"scenario": "nope", "fault": "cpu"}), 404, "not_found")
    post_scn(client, "all_attempts_fail", "cpu")
    r = client.post("/api/demo/reset")
    assert r.status_code == 200 and r.json()["state"]["cpu"] == 22.0
    assert client.get("/api/incidents/active").json() == []
    assert client.get("/api/incidents").json()["total"] == 2      # history retained
    assert len(client.get("/api/demo/history").json()) == 2
    rec = client.post("/api/demo/recover", json={"fault": "cpu"})
    assert rec.status_code == 200


def test_openapi_documents_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/health", "/api/metrics/current", "/api/incidents", "/api/remediation/{remediation_id}/approve",
              "/api/demo/scenario", "/api/config/thresholds", "/api/activity-logs", "/api/verification"):
        assert p in paths, p


def test_unknown_route_uses_error_format(client):
    assert client.get("/api/nope").status_code == 404
