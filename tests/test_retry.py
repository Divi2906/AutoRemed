from remediation.retry import execute_with_retries


def test_retry_stops_after_first_success():
    outcomes = [
        {"execution_status": "success", "message": "Success on first attempt"}
    ]

    def fake_executor(approval_request):
        return outcomes.pop(0)

    approval = {"approval_status": "approved"}

    result = execute_with_retries(approval, executor_fn=fake_executor)

    assert result["execution_status"] == "success"
    assert result["attempt_count"] == 1
    assert result["manual_intervention_required"] is False


def test_retry_succeeds_on_third_attempt():
    outcomes = [
        {"execution_status": "failed", "message": "Attempt 1 failed"},
        {"execution_status": "failed", "message": "Attempt 2 failed"},
        {"execution_status": "success", "message": "Attempt 3 succeeded"}
    ]

    def fake_executor(approval_request):
        return outcomes.pop(0)

    approval = {"approval_status": "approved"}

    result = execute_with_retries(approval, executor_fn=fake_executor)

    assert result["execution_status"] == "success"
    assert result["attempt_count"] == 3
    assert len(result["attempt_history"]) == 3
    assert result["manual_intervention_required"] is False


def test_retry_fails_after_three_attempts():
    outcomes = [
        {"execution_status": "failed", "message": "Attempt 1 failed"},
        {"execution_status": "failed", "message": "Attempt 2 failed"},
        {"execution_status": "failed", "message": "Attempt 3 failed"}
    ]

    def fake_executor(approval_request):
        return outcomes.pop(0)

    approval = {"approval_status": "approved"}

    result = execute_with_retries(approval, executor_fn=fake_executor)

    assert result["execution_status"] == "failed"
    assert result["attempt_count"] == 3
    assert len(result["attempt_history"]) == 3
    assert result["manual_intervention_required"] is True
    assert "Manual intervention required" in result["message"]