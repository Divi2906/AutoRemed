from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

ENV_REAL = "real_host"
ENV_SIM = "simulation"
ENV_LABELS = {ENV_REAL: "REAL HOST", ENV_SIM: "SIMULATION"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=str, sort_keys=True)


def loads(raw: str | None, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default
    return json.loads(raw)


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def duration_ms(start_iso: str, end_iso: str) -> int:
    return int((parse_ts(end_iso) - parse_ts(start_iso)).total_seconds() * 1000)
