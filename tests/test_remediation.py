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