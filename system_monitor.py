
import psutil


def get_system_metrics():
    """Collect CPU, memory, and disk usage from this computer."""

    cpu_usage = psutil.cpu_percent(interval=1)

    memory = psutil.virtual_memory()
    memory_usage = memory.percent

    disk = psutil.disk_usage("C:\\")
    disk_usage = disk.percent

    metrics = {
        "cpu": cpu_usage,
        "memory": memory_usage,
        "disk": disk_usage
    }

    return metrics


if __name__ == "__main__":
    system_metrics = get_system_metrics()

    print("AutoRemed - System Monitoring")
    print("-----------------------------")
    print(f"CPU Usage: {system_metrics['cpu']}%")
    print(f"Memory Usage: {system_metrics['memory']}%")
    print(f"Disk Usage: {system_metrics['disk']}%")
