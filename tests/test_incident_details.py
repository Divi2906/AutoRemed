
import unittest

from incident_details import build_incident_details


class TestIncidentDetails(unittest.TestCase):

    def test_cpu_incident_details(self):
        metrics = {"cpu": 96, "memory": 50, "disk": 40}
        incidents = ["HIGH CPU USAGE"]

        result = build_incident_details(metrics, incidents)

        self.assertEqual(result[0]["metric"], "cpu")
        self.assertEqual(result[0]["actual_value"], 96)
        self.assertEqual(result[0]["threshold"], 90)
        self.assertEqual(result[0]["severity"], "high")

    def test_memory_incident_details(self):
        metrics = {"cpu": 50, "memory": 95, "disk": 40}
        incidents = ["HIGH MEMORY USAGE"]

        result = build_incident_details(metrics, incidents)

        self.assertEqual(result[0]["metric"], "memory")
        self.assertEqual(result[0]["actual_value"], 95)
        self.assertEqual(result[0]["severity"], "high")

    def test_disk_incident_details(self):
        metrics = {"cpu": 50, "memory": 50, "disk": 98}
        incidents = ["CRITICAL DISK USAGE"]

        result = build_incident_details(metrics, incidents)

        self.assertEqual(result[0]["metric"], "disk")
        self.assertEqual(result[0]["actual_value"], 98)
        self.assertEqual(result[0]["threshold"], 95)
        self.assertEqual(result[0]["severity"], "critical")

    def test_no_incidents(self):
        metrics = {"cpu": 40, "memory": 50, "disk": 60}

        result = build_incident_details(metrics, [])

        self.assertEqual(result, [])

    def test_multiple_incidents(self):
        metrics = {"cpu": 96, "memory": 95, "disk": 98}
        incidents = [
            "HIGH CPU USAGE",
            "HIGH MEMORY USAGE",
            "CRITICAL DISK USAGE"
        ]

        result = build_incident_details(metrics, incidents)

        self.assertEqual(len(result), 3)
        self.assertEqual(
            [item["severity"] for item in result],
            ["high", "high", "critical"]
        )

    def test_unknown_incident(self):
        metrics = {"cpu": 50, "memory": 50, "disk": 50}

        with self.assertRaises(ValueError):
            build_incident_details(metrics, ["UNKNOWN INCIDENT"])


if __name__ == "__main__":
    unittest.main()
