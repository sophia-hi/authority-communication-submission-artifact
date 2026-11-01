"""Small shared cause-to-treatment map for collection failures."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


INFRASTRUCTURE_RERUN_CATEGORIES = {
    "provider_network_failure",
    "credential_failure",
    "billing_credit_failure",
    "model_route_unavailable",
    "process_interruption",
}


@dataclass(frozen=True)
class FailureDisposition:
    category: str
    treatment: str


def _status_code(error: BaseException) -> int | None:
    value: Any = getattr(error, "status_code", None)
    return value if isinstance(value, int) else None


def _text(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}".lower()


def _structured_code(error: BaseException) -> str | None:
    """Read an API error code without inferring one from prose."""
    direct = getattr(error, "code", None)
    if isinstance(direct, str) and direct:
        return direct.lower()
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        nested = body.get("error")
        for value in (body.get("code"),
                      nested.get("code") if isinstance(nested, dict) else None):
            if isinstance(value, str) and value:
                return value.lower()
    turn = getattr(error, "model_turn", None)
    response_error = getattr(turn, "response_error", None)
    if isinstance(response_error, dict):
        value = response_error.get("code")
        if isinstance(value, str) and value:
            return value.lower()
    return None


def classify_failure(error: BaseException) -> FailureDisposition:
    """Classify a cause without converting unknown code faults to infrastructure."""
    name = type(error).__name__
    status = _status_code(error)
    code = _structured_code(error)

    if name == "EmergencyGuardError":
        return FailureDisposition(
            "emergency_guard_exhaustion", "organizational_terminal")
    if name == "ModelOutputLimitError":
        return FailureDisposition(
            "output_limit_cutoff", "organizational_terminal")
    if name == "ModelContextLengthError" or code in {
            "context_length_exceeded", "context_window_exceeded"}:
        return FailureDisposition(
            "context_length_exhaustion", "organizational_terminal")
    if name == "ModelResponseFilteredError":
        return FailureDisposition(
            "model_response_filtered", "organizational_terminal")
    if name == "ProviderIncompleteResponseError":
        if code == "server_error":
            return FailureDisposition(
                "provider_network_failure", "inspection_required")
        return FailureDisposition(
            "provider_incomplete_unknown", "stop_and_inspect")
    if name in {"AgentInterfaceError", "ProtocolError"}:
        return FailureDisposition(
            "invalid_model_action", "organizational_terminal")
    if name == "TransientRequestRetriesExhausted":
        return FailureDisposition(
            "provider_network_failure", "inspection_required")
    if status in {401, 403}:
        return FailureDisposition("credential_failure", "inspection_required")
    if status == 402:
        return FailureDisposition("billing_credit_failure", "inspection_required")
    if status == 404:
        return FailureDisposition("model_route_unavailable", "inspection_required")
    if status in {408, 429} or (isinstance(status, int) and 500 <= status <= 599):
        return FailureDisposition(
            "provider_network_failure", "inspection_required")
    if isinstance(status, int) and 400 <= status <= 499:
        return FailureDisposition("api_configuration_error", "stop_and_inspect")
    if name in {"APIConnectionError", "APITimeoutError", "RateLimitError"}:
        return FailureDisposition(
            "provider_network_failure", "inspection_required")
    if name == "LiveCellInfrastructureError":
        return FailureDisposition(
            "model_route_unavailable", "inspection_required")
    if name in {"KeyboardInterrupt", "CancelledError", "SystemExit"}:
        return FailureDisposition("process_interruption", "inspection_required")
    if name == "LiveCellError":
        return FailureDisposition("internal_protocol_error", "stop_and_inspect")
    return FailureDisposition("unexpected_exception", "stop_and_inspect")


def is_rerun_eligible(category: str) -> bool:
    return category in INFRASTRUCTURE_RERUN_CATEGORIES
