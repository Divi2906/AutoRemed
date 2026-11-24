from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for errors that map to a clean HTTP response."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message)
        self.message = message
        self.details = details


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class InvalidTransition(Conflict):
    code = "invalid_transition"


class AttemptLimitReached(Conflict):
    code = "attempt_limit_reached"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_error"


class SafetyViolation(AppError):
    """Raised when something would act outside the simulation sandbox."""

    status_code = 403
    code = "safety_violation"


class ExecutorDisabled(SafetyViolation):
    code = "executor_disabled"
