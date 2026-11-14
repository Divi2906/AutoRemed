from pathlib import Path
import json
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from main import detect_incidents
from validators import validate_metrics
from incident_details import build_incident_details
from system_monitor import get_system_metrics

from remediation.rules import get_supported_action
from remediation.approval import request_approval, process_approval
from remediation.executor import execute_remediation
from remediation.action_logs import create_action_log, save_action_log


app = FastAPI(
    title="AutoRemed API",
    description="Backend API for incident detection and automated remediation",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DetectionRequest(BaseModel):
    service: str = Field(min_length=1)
    metrics: dict[str, Any]


class ApprovalRequest(BaseModel):
    incident_id: str = Field(min_length=1)
    incident: dict[str, Any]
    decision: str = Field(min_length=1)


# Prototype storage: approval requests remain available while this API process runs.
# Activity logs are persisted in logs/actions.jsonl.
approval_requests: dict[str, dict[str, Any]] = {}


def process_metrics(service: str, metrics: dict):
    """Validate metrics and generate structured incident results."""
    validated_metrics = validate_metrics(metrics)

    incidents = detect_incidents(
        validated_metrics["cpu"],
        validated_metrics["memory"],
        validated_metrics["disk"]
    )

    incident_details = build_incident_details(validated_metrics, incidents)

    for index, incident in enumerate(incident_details, start=1):
        incident["id"] = f"INC-{index:03d}"
        incident["service"] = service

    return {
        "status": "success",
        "service": service,
        "metrics": validated_metrics,
        "incidents": incident_details,
        "incident_count": len(incident_details)
    }


@app.get("/")
def home():
    return {
        "message": "Welcome to AutoRemed API",
        "status": "running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "AutoRemed"
    }


@app.post("/api/v1/detect")
def detect(request: DetectionRequest):
    try:
        return process_metrics(request.service, request.metrics)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/monitor")
def monitor():
    try:
        metrics = get_system_metrics()
        return process_metrics("local-windows-system", metrics)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/api/v1/approval")
def handle_approval(request: ApprovalRequest):
    """Record a human decision and simulate an approved remediation action."""
    decision = request.decision.strip().lower()
    if decision not in {"approve", "reject"}:
        raise HTTPException(
            status_code=422,
            detail="Decision must be 'approve' or 'reject'."
        )

    incident = dict(request.incident)
    incident.setdefault("service", "AutoRemed")

    # Prevent the same incident ID from being approved/rejected more than once.
    if request.incident_id in approval_requests:
        existing = approval_requests[request.incident_id]
        return {
            "success": False,
            "approval_status": existing["approval_status"],
            "message": "This incident approval has already been processed."
        }

    action_info = get_supported_action(incident)
    if not action_info.get("supported"):
        raise HTTPException(
            status_code=422,
            detail=action_info.get("reason", "No supported remediation action.")
        )

    approval_request = request_approval(
        incident,
        action_info["action"]
    )

    approval_result = process_approval(approval_request, decision)
    if not approval_result.get("success"):
        raise HTTPException(status_code=409, detail=approval_result["message"])

    # Executor itself blocks anything that has not been approved.
    if decision == "approve":
        execution_result = execute_remediation(approval_request)
    else:
        execution_result = {
            "execution_status": "not_executed",
            "message": "Remediation was rejected; no action was executed."
        }

    log_entry = create_action_log(
        incident,
        approval_request,
        execution_result
    )
    save_action_log(log_entry)

    approval_requests[request.incident_id] = approval_request

    return {
        "success": True,
        "incident_id": request.incident_id,
        "approval_status": approval_request["approval_status"],
        "execution_status": execution_result.get("execution_status"),
        "proposed_action": approval_request["proposed_action"],
        "message": approval_result["message"],
        "execution_message": execution_result.get("message")
    }


@app.get("/api/v1/activity-logs")
def get_activity_logs():
    """Return persisted action log records, newest first."""
    log_path = Path("logs/actions.jsonl")

    if not log_path.exists():
        return {"status": "success", "logs": []}

    logs = []
    try:
        with log_path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue
                try:
                    logs.append(json.loads(line))
                except json.JSONDecodeError:
                    # Ignore an incomplete/corrupt line rather than failing all logs.
                    continue
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail=f"Could not read activity logs: {error}"
        )

    logs.reverse()
    return {"status": "success", "logs": logs}
