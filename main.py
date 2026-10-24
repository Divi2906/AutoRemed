
print("Welcome to AutoRemed!")
print("My DevOps remediation project has started.")
print("System ready.")

def detect_incident(cpu, memory, disk):
    """Detect incidents using predefined thresholds."""

    if cpu >= 90:
        return "HIGH CPU USAGE"

    elif memory >= 90:
        return "HIGH MEMORY USAGE"

    elif disk >= 95:
        return "CRITICAL DISK USAGE"

    else:
        return "SYSTEM HEALTHY"


# Simulated server metrics
cpu_usage = 96
memory_usage = 55
disk_usage = 40

print("=== AutoRemed Incident Detector ===")
print(f"CPU Usage: {cpu_usage}%")
print(f"Memory Usage: {memory_usage}%")
print(f"Disk Usage: {disk_usage}%")

incident = detect_incident(
    cpu_usage,
    memory_usage,
    disk_usage
)

print(f"\nDetection Result: {incident}")
