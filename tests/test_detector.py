import unittest
from main import detect_incident,detect_incidents


class TestIncidentDetector(unittest.TestCase):

    def test_high_cpu(self):
        result = detect_incident(95, 50, 40)
        self.assertEqual(result, "HIGH CPU USAGE")

    def test_high_memory(self):
        result = detect_incident(50, 95, 40)
        self.assertEqual(result, "HIGH MEMORY USAGE")

    def test_critical_disk(self):
        result = detect_incident(50, 40, 96)
        self.assertEqual(result, "CRITICAL DISK USAGE")

    def test_system_healthy(self):
        result = detect_incident(50, 50, 50)
        self.assertEqual(result, "SYSTEM HEALTHY")

    def test_cpu_has_priority(self):
        result = detect_incident(95, 95, 96)
        self.assertEqual(result, "HIGH CPU USAGE")

    def test_multiple_incidents(self):
        result = detect_incidents(96, 95, 98)
        self.assertEqual(
        result,
        [
            "HIGH CPU USAGE",
            "HIGH MEMORY USAGE",
            "CRITICAL DISK USAGE"
        ]
    )
    def test_no_incidents(self):
        result = detect_incidents(40, 50, 60)
        self.assertEqual(result, [])


    def test_only_memory_incident(self):
        result = detect_incidents(50, 95, 60)
        self.assertEqual(result, ["HIGH MEMORY USAGE"])


if __name__ == "__main__":
    unittest.main()