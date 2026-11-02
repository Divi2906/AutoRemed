
def detect_incident(cpu, memory, disk):
    """Detect the first incident using existing priority rules."""

    if cpu >= 90:
        return "HIGH CPU USAGE"
    elif memory >= 90:
        return "HIGH MEMORY USAGE"
    elif disk >= 95:
        return "CRITICAL DISK USAGE"
    else:
        return "SYSTEM HEALTHY"


def detect_incidents(cpu, memory, disk):
    """Detect all incidents instead of stopping at the first one."""

    incidents = []

    if cpu >= 90:
        incidents.append("HIGH CPU USAGE")

    if memory >= 90:
        incidents.append("HIGH MEMORY USAGE")

    if disk >= 95:
        incidents.append("CRITICAL DISK USAGE")

    return incidents


def main():
    # Simulated server metrics
    cpu_usage = 96
    memory_usage = 55
    disk_usage = 40

    print("Welcome to AutoRemed!")
    print("My DevOps remediation project has started.")
    print("System ready.")

    print("=== AutoRemed Incident Detector ===")
    print(f"CPU Usage: {cpu_usage}%")
    print(f"Memory Usage: {memory_usage}%")
    print(f"Disk Usage: {disk_usage}%")

    incidents = detect_incidents(
        cpu_usage,
        memory_usage,
        disk_usage
    )

    if incidents:
        print("\nDetection Results:")
        for incident in incidents:
            print(incident)
    else:
        print("\nSYSTEM HEALTHY")


if __name__ == "__main__":
    main()
