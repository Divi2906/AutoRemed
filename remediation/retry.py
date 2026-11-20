
from remediation.executor import execute_remediation


def execute_with_retries(approval_request, max_attempts=3, executor_fn=None):
    """
    Execute an approved simulated remediation up to max_attempts times.

    Stops immediately on success.
    If every attempt fails, manual intervention is required.
    """

    if approval_request.get("approval_status") != "approved":
        return {
            "execution_status": "blocked",
            "attempt_count": 0,
            "attempt_history": [],
            "manual_intervention_required": False,
            "message": "Remediation cannot execute without human approval."
        }

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    executor = executor_fn or execute_remediation

    attempt_history = []

    for attempt_number in range(1, max_attempts + 1):
        result = executor(approval_request)

        attempt_history.append({
            "attempt": attempt_number,
            "execution_status": result.get("execution_status"),
            "message": result.get("message")
        })

        # Stop immediately if successful.
        if result.get("execution_status") == "success":
            return {
                "execution_status": "success",
                "attempt_count": attempt_number,
                "attempt_history": attempt_history,
                "manual_intervention_required": False,
                "message": "Remediation succeeded."
            }

        # Do not retry blocked actions.
        if result.get("execution_status") == "blocked":
            return {
                "execution_status": "blocked",
                "attempt_count": attempt_number,
                "attempt_history": attempt_history,
                "manual_intervention_required": False,
                "message": result.get("message", "Remediation was blocked.")
            }

    return {
        "execution_status": "failed",
        "attempt_count": len(attempt_history),
        "attempt_history": attempt_history,
        "manual_intervention_required": True,
        "message": f"Remediation failed after {max_attempts} attempts. Manual intervention required."
    }
