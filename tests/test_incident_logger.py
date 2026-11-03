import json
import os
import tempfile
import unittest
from unittest.mock import patch

from incident_logger import log_incidents


class TestIncidentLogger(unittest.TestCase):

    def test_log_incidents_saves_data(self):
        incident_details = [
            {
                "type": "HIGH CPU USAGE",
                "metric": "cpu",
                "actual_value": 96,
                "threshold": 90,
                "severity": "high"
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = os.path.join(temp_dir, "incident_logs.json")

            with patch("incident_logger.LOG_FILE", log_file):
                log_incidents("test-service", incident_details)

            with open(log_file, "r", encoding="utf-8") as file:
                logs = json.load(file)

            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0]["service"], "test-service")
            self.assertEqual(logs[0]["type"], "HIGH CPU USAGE")
            self.assertEqual(logs[0]["actual_value"], 96)
            self.assertEqual(logs[0]["threshold"], 90)

    def test_empty_incidents_do_not_create_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = os.path.join(temp_dir, "incident_logs.json")

            with patch("incident_logger.LOG_FILE", log_file):
                log_incidents("test-service", [])

            self.assertFalse(os.path.exists(log_file))


if __name__ == "__main__":
    unittest.main()