from remediation.rules import get_supported_action
from remediation.executor import execute_remediation


def test_high_cpu_incident():
    incident = {
        "type": "HIGH CPU USAGE",
        "metric": "cpu",
        "actual_value": 96,
        "threshold": 90,
        "severity": "high"
    }

    result = get_supported_action(incident)

    assert result["supported"] is True
    assert result["action"] == "SIMULATE_SERVICE_RESTART"


def test_unsupported_incident():
    incident = {
        "type": "UNKNOWN INCIDENT",
        "metric": "cpu",
        "actual_value": 96,
        "threshold": 90,
        "severity": "high"
    }

    result = get_supported_action(incident)

    assert result["supported"] is False

from remediation.approval import request_approval, process_approval


def test_approval_granted():
    incident = {
        "type": "HIGH CPU USAGE",
        "service": "payment-api"
    }

    approval = request_approval(
        incident,
        "SIMULATE_SERVICE_RESTART"
    )

    assert approval["approval_status"] == "pending"

    result = process_approval(approval, "approve")

    assert result["approval_status"] == "approved"


def test_approval_rejected():
    incident = {
        "type": "HIGH CPU USAGE",
        "service": "payment-api"
    }

    approval = request_approval(
        incident,
        "SIMULATE_SERVICE_RESTART"
    )

    result = process_approval(approval, "reject")

    assert result["approval_status"] == "rejected"

from remediation.executor import execute_remediation


def test_execution_after_approval():
    approval_request = {
        "approval_status": "approved",
        "proposed_action": "SIMULATE_SERVICE_RESTART"
    }

    result = execute_remediation(approval_request)

    assert result["execution_status"] == "success"


def test_execution_without_approval():
    approval_request = {
        "approval_status": "pending",
        "proposed_action": "SIMULATE_SERVICE_RESTART"
    }

    result = execute_remediation(approval_request)

    assert result["execution_status"] == "blocked"


def test_execution_after_rejection():
    approval_request = {
        "approval_status": "rejected",
        "proposed_action": "SIMULATE_SERVICE_RESTART"
    }

    result = execute_remediation(approval_request)

    assert result["execution_status"] == "blocked"


def test_unsupported_execution_action():
    approval_request = {
        "approval_status": "approved",
        "proposed_action": "DELETE_SYSTEM_FILES"
    }

    result = execute_remediation(approval_request)

    assert result["execution_status"] == "failed"


from remediation.action_logs import create_action_log, save_action_log


def test_create_action_log():

    incident = {
        "type": "HIGH CPU USAGE",
        "metric": "cpu",
        "service": "payment-api",
        "severity": "high"
    }

    approval_request = {
        "proposed_action": "SIMULATE_SERVICE_RESTART",
        "approval_status": "approved"
    }

    execution_result = {
        "execution_status": "success",
        "message": "Simulated service restart successful."
    }

    log = create_action_log(
        incident,
        approval_request,
        execution_result
    )

    assert log["incident_type"] == "HIGH CPU USAGE"
    assert log["approval_status"] == "approved"
    assert log["execution_status"] == "success"
    assert log["timestamp"] is not None


def test_save_action_log(tmp_path):

    log_entry = {
        "incident_type": "HIGH CPU USAGE",
        "approval_status": "approved",
        "execution_status": "success"
    }

    file_path = tmp_path / "actions.jsonl"

    result = save_action_log(log_entry, file_path)

    assert result["success"] is True
    assert file_path.exists()

    saved_data = file_path.read_text(encoding="utf-8")

    assert "HIGH CPU USAGE" in saved_data