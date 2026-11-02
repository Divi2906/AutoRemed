
import math


REQUIRED_METRICS = ["cpu", "memory", "disk"]


def validate_metrics(metrics):
    """Validate CPU, memory and disk metric values."""

    if not isinstance(metrics, dict):
        raise ValueError("Metrics must be a JSON object")

    validated = {}

    for metric in REQUIRED_METRICS:

        if metric not in metrics:
            raise ValueError(f"Missing required metric: {metric}")

        value = metrics[metric]

        # Reject booleans and non-numeric values
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{metric} must be a number")

        if not math.isfinite(value):
            raise ValueError(f"{metric} must be finite")

        if not 0 <= value <= 100:
            raise ValueError(f"{metric} must be between 0 and 100")

        validated[metric] = value

    return validated
