def request_approval(incident, proposed_action):
    """
    Create an approval request for a remediation action.
    The action is NOT executed here.
    """

    return {
        "incident_type": incident.get("type"),
        "service": incident.get("service", "unknown"),
        "proposed_action": proposed_action,
        "approval_status": "pending"
    }


def process_approval(approval_request, decision):
    """
    Process the human approval or rejection decision.
    """

    if approval_request["approval_status"] != "pending":
        return {
            "success": False,
            "message": "This request has already been processed."
        }

    if decision == "approve":
        approval_request["approval_status"] = "approved"

        return {
            "success": True,
            "approval_status": "approved",
            "message": "Human approval granted."
        }

    elif decision == "reject":
        approval_request["approval_status"] = "rejected"

        return {
            "success": True,
            "approval_status": "rejected",
            "message": "Human approval rejected."
        }

    return {
        "success": False,
        "message": "Invalid approval decision."
    }