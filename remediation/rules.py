SUPPORTED_ACTIONS = {
    "HIGH CPU USAGE": {
        "metric": "cpu",
        "action": "SIMULATE_SERVICE_RESTART",
        "description": "Simulate restarting the affected service."
    },
    "HIGH MEMORY USAGE": {
        "metric": "memory",
        "action": "SIMULATE_CACHE_CLEANUP",
        "description": "Simulate clearing the application cache."
    },
    "CRITICAL DISK USAGE": {
        "metric": "disk",
        "action": "SIMULATE_TEMP_FILE_CLEANUP",
        "description": "Simulate cleaning approved temporary files."
    }
}


def get_supported_action(incident):
    """
    Find a supported remediation action for a detected incident.
    Does not execute any action.
    """

    incident_type = incident.get("type")
    metric = incident.get("metric")

    rule = SUPPORTED_ACTIONS.get(incident_type)

    if rule is None:
        return {
            "supported": False,
            "reason": "Unsupported incident type."
        }

    if rule["metric"] != metric:
        return {
            "supported": False,
            "reason": "Incident type and metric do not match."
        }

    return {
        "supported": True,
        "action": rule["action"],
        "description": rule["description"]
    }