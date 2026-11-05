import json
from datetime import datetime, timezone
from pathlib import Path


def create_action_log(incident, approval_request, execution_result):
    """
    Create a record of a remediation attempt.
    """

    log_entry = {
        "incident_type": incident.get("type"),
        "metric": incident.get("metric"),
        "service": incident.get("service", "unknown"),
        "severity": incident.get("severity"),
        "proposed_action": approval_request.get("proposed_action"),
        "approval_status": approval_request.get("approval_status"),
        "execution_status": execution_result.get("execution_status"),
        "message": execution_result.get("message"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    return log_entry


def save_action_log(log_entry, file_path="logs/actions.jsonl"):
    """
    Save the action log as a JSON line.
    Each remediation attempt gets a separate record.
    """

    log_file = Path(file_path)

    log_file.parent.mkdir(parents=True, exist_ok=True)

    with log_file.open("a", encoding="utf-8") as file:
        file.write(json.dumps(log_entry) + "\n")

    return {
        "success": True,
        "message": "Action log saved successfully."
    }