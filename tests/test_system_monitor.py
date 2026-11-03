
import unittest

from system_monitor import get_system_metrics
from main import detect_incidents
from validators import validate_metrics


class TestSystemMonitor(unittest.TestCase):

    def test_real_system_monitoring(self):
        metrics = get_system_metrics()

        print("\nCollected system metrics:", metrics)

        # Validate collected metrics
        validate_metrics(metrics)

        # Detect incidents
        incidents = detect_incidents(
            metrics["cpu"],
            metrics["memory"],
            metrics["disk"]
        )

        print("Detected incidents:", incidents)

        self.assertIn("cpu", metrics)
        self.assertIn("memory", metrics)
        self.assertIn("disk", metrics)


if __name__ == "__main__":
    unittest.main()
