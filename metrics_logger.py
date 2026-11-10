
import json
import os
from datetime import datetime, timezone


METRICS_FILE = "metrics_history.json"


def log_metrics(metrics):
    """
    Save CPU, memory and disk readings with a UTC timestamp.
    Append new readings without deleting existing history.
    """

    if not isinstance(metrics, dict):
        raise ValueError("Metrics must be a dictionary")

    required_metrics = ("cpu", "memory", "disk")

    for metric in required_metrics:
        if metric not in metrics:
            raise ValueError(f"Missing metric: {metric}")

    timestamp = datetime.now(timezone.utc).isoformat()

    log_entry = {
        "timestamp": timestamp,
        "cpu": metrics["cpu"],
        "memory": metrics["memory"],
        "disk": metrics["disk"]
    }

    if os.path.exists(METRICS_FILE):
        try:
            with open(METRICS_FILE, "r", encoding="utf-8") as file:
                history = json.load(file)

            if not isinstance(history, list):
                raise ValueError("Metrics history must be a JSON list")

        except json.JSONDecodeError as error:
            raise ValueError("Metrics history contains invalid JSON") from error
    else:
        history = []

    history.append(log_entry)

    with open(METRICS_FILE, "w", encoding="utf-8") as file:
        json.dump(history, file, indent=4)

    print("Historical metrics saved successfully.")
