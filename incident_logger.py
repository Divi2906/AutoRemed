
import json
import os

from datetime import datetime, timezone


LOG_FILE = "incident_logs.json"


def log_incidents(service, incident_details):
    """
    Save detected incidents to a JSON file.
    """

    if not incident_details:
        return

    # Create timestamp for this monitoring cycle
    timestamp = datetime.now(timezone.utc).isoformat()

    # Load existing logs if the file exists
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as file:
                logs = json.load(file)
        except (json.JSONDecodeError, OSError):
            logs = []
    else:
        logs = []

    # Add each detected incident
    for incident in incident_details:
        log_entry = {
            "timestamp": timestamp,
            "service": service,
            "type": incident["type"],
            "metric": incident["metric"],
            "actual_value": incident["actual_value"],
            "threshold": incident["threshold"],
            "severity": incident["severity"]
        }

        logs.append(log_entry)

    # Save updated logs
    with open(LOG_FILE, "w", encoding="utf-8") as file:
        json.dump(logs, file, indent=4)

    print(f"Logged {len(incident_details)} incident(s).")
