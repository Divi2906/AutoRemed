
INCIDENT_RULES = {
    "HIGH CPU USAGE": {
        "metric": "cpu",
        "threshold": 90,
        "severity": "high"
    },
    "HIGH MEMORY USAGE": {
        "metric": "memory",
        "threshold": 90,
        "severity": "high"
    },
    "CRITICAL DISK USAGE": {
        "metric": "disk",
        "threshold": 95,
        "severity": "critical"
    }
}


def build_incident_details(metrics, incidents):
    """Convert detected incident names into structured details."""
    incident_details = []

    for incident in incidents:
        if incident not in INCIDENT_RULES:
            raise ValueError(f"Unknown incident type: {incident}")

        rule = INCIDENT_RULES[incident]
        metric_name = rule["metric"]

        incident_details.append({
            "type": incident,
            "metric": metric_name,
            "actual_value": metrics[metric_name],
            "threshold": rule["threshold"],
            "severity": rule["severity"]
        })

    return incident_details
