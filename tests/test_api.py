
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import json
import tempfile
from pathlib import Path
from api import app

client = TestClient(app)


class TestAutoRemedAPI(unittest.TestCase):

    def test_health_endpoint(self):
        response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")

    
    def test_successful_incident_detection(self):
        response = client.post(
        "/api/v1/detect",
        json={
            "service": "payment-api",
            "metrics": {
                "cpu": 96,
                "memory": 95,
                "disk": 98
            }
        }
        )

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertEqual(data["status"], "success")
        self.assertEqual(data["incident_count"], 3)

        incidents = data["incidents"]

        self.assertEqual(incidents[0]["type"], "HIGH CPU USAGE")
        self.assertEqual(incidents[0]["metric"], "cpu")
        self.assertEqual(incidents[0]["actual_value"], 96)
        self.assertEqual(incidents[0]["threshold"], 90)
        self.assertEqual(incidents[0]["severity"], "high")

        self.assertEqual(incidents[1]["severity"], "high")
        self.assertEqual(incidents[2]["severity"], "critical")


        
    def test_healthy_system(self):
        response = client.post(
            "/api/v1/detect",
            json={
                "service": "payment-api",
                "metrics": {
                    "cpu": 40,
                    "memory": 50,
                    "disk": 60
                }
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["incident_count"], 0)
        self.assertEqual(response.json()["incidents"], [])

    def test_invalid_cpu_value(self):
        response = client.post(
            "/api/v1/detect",
            json={
                "service": "payment-api",
                "metrics": {
                    "cpu": 150,
                    "memory": 50,
                    "disk": 60
                }
            }
        )

        self.assertEqual(response.status_code, 422)

    def test_missing_metric(self):
        response = client.post(
            "/api/v1/detect",
            json={
                "service": "payment-api",
                "metrics": {
                    "cpu": 50,
                    "memory": 60
                }
            }
        )

        self.assertEqual(response.status_code, 422)
        
    @patch("api.get_system_metrics")
    def test_monitor_endpoint_success(self, mock_metrics):
        mock_metrics.return_value = {
            "cpu": 40,
            "memory": 50,
            "disk": 60
        }

        response = client.post("/api/v1/monitor")

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertEqual(data["status"], "success")
        self.assertEqual(data["service"], "local-windows-system")
        self.assertEqual(data["incident_count"], 0)
        self.assertEqual(data["incidents"], [])

    @patch("api.get_system_metrics")
    def test_monitor_endpoint_detects_incidents(self, mock_metrics):
        mock_metrics.return_value = {
            "cpu": 96,
            "memory": 50,
            "disk": 40
        }

        response = client.post("/api/v1/monitor")

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertEqual(data["incident_count"], 1)
        self.assertEqual(data["incidents"][0]["type"], "HIGH CPU USAGE")
        self.assertEqual(data["incidents"][0]["actual_value"], 96)

    @patch("api.get_system_metrics")
    def test_monitor_endpoint_invalid_metrics(self, mock_metrics):
        mock_metrics.return_value = {
            "cpu": 150,
            "memory": 50,
            "disk": 40
        }

        response = client.post("/api/v1/monitor")

        self.assertEqual(response.status_code, 422)


    @patch("api.save_action_log")
    def test_approval_endpoint_approved(self, mock_save_log):
        response = client.post(
            "/api/v1/approval",
            json={
                "incident_id": "TEST-APPROVE-001",
                "incident": {
                    "type": "HIGH CPU USAGE",
                    "metric": "cpu",
                    "service": "payment-api",
                    "severity": "high"
                },
                "decision": "approve"
            }
        )

        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["approval_status"], "approved")
        self.assertEqual(data["execution_status"], "success")
        self.assertEqual(data["proposed_action"], "SIMULATE_SERVICE_RESTART")
        mock_save_log.assert_called_once()

    @patch("api.save_action_log")
    def test_approval_endpoint_rejected(self, mock_save_log):
        response = client.post(
            "/api/v1/approval",
            json={
                "incident_id": "TEST-REJECT-001",
                "incident": {
                    "type": "HIGH CPU USAGE",
                    "metric": "cpu",
                    "service": "payment-api",
                    "severity": "high"
                },
                "decision": "reject"
            }
        )

        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["approval_status"], "rejected")
        self.assertEqual(data["execution_status"], "not_executed")
        mock_save_log.assert_called_once()

    def test_approval_endpoint_invalid_decision(self):
        response = client.post(
            "/api/v1/approval",
            json={
                "incident_id": "TEST-INVALID-001",
                "incident": {
                    "type": "HIGH CPU USAGE",
                    "metric": "cpu",
                    "service": "payment-api"
                },
                "decision": "maybe"
            }
        )

        self.assertEqual(response.status_code, 422)
    @patch("api.save_action_log")
    def test_duplicate_approval_is_prevented(self, mock_save_log):
        payload = {
            "incident_id": "TEST-DUPLICATE-001",
            "incident": {
                "type": "HIGH CPU USAGE",
                "metric": "cpu",
                "service": "payment-api",
                "severity": "high"
            },
            "decision": "approve"
        }

        first_response = client.post("/api/v1/approval", json=payload)
        second_response = client.post("/api/v1/approval", json=payload)

        self.assertEqual(first_response.status_code, 200)
        self.assertTrue(first_response.json()["success"])

        self.assertEqual(second_response.status_code, 200)
        self.assertFalse(second_response.json()["success"])
        self.assertIn("already been processed", second_response.json()["message"])

        # The action log should be created only once.
        mock_save_log.assert_called_once()

    @patch("api.Path")
    def test_activity_logs_endpoint(self, mock_path):
        log_entries = [
            {
                "incident_type": "HIGH CPU USAGE",
                "approval_status": "approved",
                "execution_status": "success"
            },
            {
                "incident_type": "HIGH MEMORY USAGE",
                "approval_status": "rejected",
                "execution_status": "not_executed"
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "actions.jsonl"

            with log_file.open("w", encoding="utf-8") as file:
                for entry in log_entries:
                    file.write(json.dumps(entry) + "\n")

            mock_path.return_value = log_file

            response = client.get("/api/v1/activity-logs")

        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["logs"]), 2)

        # Logs should be returned newest first.
        self.assertEqual(data["logs"][0]["approval_status"], "rejected")
        self.assertEqual(data["logs"][1]["approval_status"], "approved")

if __name__ == "__main__":
    unittest.main()
