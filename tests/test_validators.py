
import unittest
from validators import validate_metrics


class TestMetricValidation(unittest.TestCase):

    def test_valid_metrics(self):
        metrics = {
            "cpu": 95,
            "memory": 70,
            "disk": 50
        }

        self.assertEqual(validate_metrics(metrics), metrics)

    def test_missing_metric(self):
        metrics = {"cpu": 50, "memory": 60}

        with self.assertRaises(ValueError):
            validate_metrics(metrics)

    def test_negative_value(self):
        metrics = {"cpu": -5, "memory": 50, "disk": 50}

        with self.assertRaises(ValueError):
            validate_metrics(metrics)

    def test_value_above_100(self):
        metrics = {"cpu": 150, "memory": 50, "disk": 50}

        with self.assertRaises(ValueError):
            validate_metrics(metrics)

    def test_string_value(self):
        metrics = {"cpu": "high", "memory": 50, "disk": 50}

        with self.assertRaises(ValueError):
            validate_metrics(metrics)

    def test_boolean_value(self):
        metrics = {"cpu": True, "memory": 50, "disk": 50}

        with self.assertRaises(ValueError):
            validate_metrics(metrics)

    def test_non_finite_value(self):
        metrics = {"cpu": float("nan"), "memory": 50, "disk": 50}

        with self.assertRaises(ValueError):
            validate_metrics(metrics)

    
    def test_positive_infinity(self):
        metrics = {"cpu": float("inf"), "memory": 50, "disk": 50}
        with self.assertRaises(ValueError):
            validate_metrics(metrics)

    def test_negative_infinity(self):
        metrics = {"cpu": float("-inf"), "memory": 50, "disk": 50}
        with self.assertRaises(ValueError):
            validate_metrics(metrics)

    def test_zero_boundary(self):
        metrics = {"cpu": 0, "memory": 0, "disk": 0}
        self.assertEqual(validate_metrics(metrics), metrics)

    def test_100_boundary(self):
        metrics = {"cpu": 100, "memory": 100, "disk": 100}
        self.assertEqual(validate_metrics(metrics), metrics)

    def test_non_dictionary_input(self):
        with self.assertRaises(ValueError):
            validate_metrics([50, 60, 70])

if __name__ == "__main__":
    unittest.main()
