
import unittest

from fastapi.testclient import TestClient
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


if __name__ == "__main__":
    unittest.main()
