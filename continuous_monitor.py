
import time
from incident_logger import log_incidents
from system_monitor import get_system_metrics
from main import detect_incidents
from incident_details import build_incident_details
from metrics_logger import log_metrics


def start_continuous_monitoring(interval=10):
    """
    Continuously collect system metrics and detect incidents.
    Runs until the user stops the program.
    """

    print("AutoRemed Continuous Monitoring Started")
    print(f"Monitoring interval: {interval} seconds")
    print("----------------------------------------")

    try:
        while True:
            # Collect current system metrics
            metrics = get_system_metrics()
            # Save historical system metrics
            log_metrics(metrics)
            # Detect incidents
            incidents = detect_incidents(
                metrics["cpu"],
                metrics["memory"],
                metrics["disk"]
            )

            # Generate detailed incident information
            incident_details = build_incident_details(
                metrics,
                incidents
            )
            
            log_incidents(
    "local-windows-system",
    incident_details
)

            print("\nSystem Metrics:")
            print(f"CPU: {metrics['cpu']}%")
            print(f"Memory: {metrics['memory']}%")
            print(f"Disk: {metrics['disk']}%")

            if incident_details:
                print("\nALERT: Incidents detected!")

                for incident in incident_details:
                    print(
                        f"{incident['type']} | "
                        f"Actual: {incident['actual_value']}% | "
                        f"Threshold: {incident['threshold']}% | "
                        f"Severity: {incident['severity']}"
                    )
            else:
                print("\nSystem Status: HEALTHY")

            print("\nNext collection in", interval, "seconds")
            time.sleep(interval)

    except KeyboardInterrupt:
        print("\nContinuous monitoring stopped.")


if __name__ == "__main__":
    start_continuous_monitoring()
