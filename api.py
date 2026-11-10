from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from metrics_logger import get_metrics_history
from main import detect_incidents
from validators import validate_metrics
from incident_details import build_incident_details
from system_monitor import get_system_metrics

app = FastAPI(
    title="AutoRemed API",
    description="Backend API for incident detection and automated remediation",
    version="1.0.0"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



class Metrics(BaseModel):
    cpu: float = Field(ge=0, le=100, strict=True)
    memory: float = Field(ge=0, le=100, strict=True)
    disk: float = Field(ge=0, le=100, strict=True)

class DetectionRequest(BaseModel):
    service: str = Field(min_length=1)
    metrics: Metrics


class IncidentResponse(BaseModel):
    type: Literal[
        "HIGH CPU USAGE",
        "HIGH MEMORY USAGE",
        "CRITICAL DISK USAGE"
    ]
    metric: Literal["cpu", "memory", "disk"]
    actual_value: int | float
    threshold: int | float
    severity: Literal["high", "critical"]


class DetectionResponse(BaseModel):
    status: Literal["success"]
    service: str
    metrics: Metrics
    incidents: list[IncidentResponse]
    incident_count: int


class HealthResponse(BaseModel):
    status: Literal["healthy"]
    service: str


class MetricHistoryEntry(BaseModel):
    timestamp: str
    cpu: float
    memory: float
    disk: float


class MetricsHistoryResponse(BaseModel):
    status: Literal["success"]
    count: int
    history: list[MetricHistoryEntry]


def process_metrics(service: str, metrics: dict):
    """Validate metrics and generate structured incident results."""

    validated_metrics = validate_metrics(metrics)

    incidents = detect_incidents(
        validated_metrics["cpu"],
        validated_metrics["memory"],
        validated_metrics["disk"]
    )

    incident_details = build_incident_details(
        validated_metrics,
        incidents
    )

    return {
        "status": "success",
        "service": service,
        "metrics": validated_metrics,
        "incidents": incident_details,
        "incident_count": len(incident_details)
    }

@app.get("/")
def home():
    return {
        "message": "Welcome to AutoRemed API",
        "status": "running"
    }


@app.get("/health", response_model=HealthResponse)
def health_check():
    return {
        "status": "healthy",
        "service": "AutoRemed"
    }


@app.post("/api/v1/detect", response_model=DetectionResponse)
def detect(request: DetectionRequest):
    try:
        return process_metrics(
            request.service,
            request.metrics.model_dump()
        )

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error)
        )

@app.post("/api/v1/monitor", response_model=DetectionResponse)
def monitor():
    try:
        # Collect actual system metrics
        metrics = get_system_metrics()

        # Process and detect incidents
        return process_metrics(
            "local-windows-system",
            metrics
        )

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error)
        )

@app.get(
    "/api/v1/metrics/history",
    response_model=MetricsHistoryResponse
)
def metrics_history():
    try:
        history = get_metrics_history()

        return {
            "status": "success",
            "count": len(history),
            "history": history
        }

    except ValueError as error:
        raise HTTPException(
            status_code=500,
            detail=str(error)
        )
