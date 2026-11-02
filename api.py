

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from main import detect_incidents
from validators import validate_metrics
from incident_details import build_incident_details

app = FastAPI(
    title="AutoRemed API",
    description="Backend API for incident detection and automated remediation",
    version="1.0.0"
)


class DetectionRequest(BaseModel):
    service: str = Field(min_length=1)
    metrics: dict[str, Any]


@app.get("/")
def home():
    return {
        "message": "Welcome to AutoRemed API",
        "status": "running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "AutoRemed"
    }


@app.post("/api/v1/detect")
def detect(request: DetectionRequest):
    try:
        # Step 1: Validate incoming metrics
        metrics = validate_metrics(request.metrics)

        # Step 2: Detect all incidents
        incidents = detect_incidents(
            metrics["cpu"],
            metrics["memory"],
            metrics["disk"]
        )

        # Step 3: Generate structured incident details
        incident_details = build_incident_details(
            metrics,
            incidents
        )

        # Step 4: Return API response
        return {
            "status": "success",
            "service": request.service,
            "incidents": incident_details,
            "incident_count": len(incident_details)
        }

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error)
        )
