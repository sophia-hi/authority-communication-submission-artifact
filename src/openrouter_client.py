"""Auditable OpenRouter Responses API adapter and request-level retry wrapper."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
import asyncio
from time import monotonic
from typing import Any, Mapping, Sequence

from openai import (APIConnectionError, APIStatusError, APITimeoutError,
                    RateLimitError)


DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class TransientRequestRetriesExhausted(RuntimeError):
    """A recognized temporary API error persisted through the retry limit."""


class ProviderResponseError(RuntimeError):
    """The provider returned a response that was not complete and usable."""


def is_transient_api_error(error: BaseException) -> bool:
    """Return true only for recognized temporary transport/provider errors."""
    if isinstance(error, (APIConnectionError, APITimeoutError, RateLimitError)):
        return True
    if isinstance(error, APIStatusError):
        status = getattr(error, "status_code", None)
        return status == 408 or status == 429 or (
            isinstance(status, int) and 500 <= status <= 599)
    return False


def _plain(value: Any) -> Any:
    """Convert SDK objects into JSON-safe values without retaining secrets."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, "model_dump"):
        return _plain(value.model_dump(mode="json", exclude_none=True))
    if hasattr(value, "__dict__"):
        return {
            str(k): _plain(v)
            for k, v in vars(value).items()
            if not str(k).startswith("_")
        }
    return str(value)


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


@dataclass(frozen=True)
class OpenRouterSettings:
    model: str
    api_key: str = field(repr=False)
    base_url: str = DEFAULT_BASE_URL
    reasoning_effort: str = "low"
    temperature: float | None = None
    max_output_tokens: int = 16_000
    timeout_s: float = 600.0
    provider_order: tuple[str, ...] = ("OpenAI",)
    allow_model_fallback: bool = False

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model must be set")
        if not self.api_key.strip():
            raise ValueError("OpenRouter API key is missing")
        if self.allow_model_fallback:
            raise ValueError("model fallback must remain disabled for this experiment")
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")

    @classmethod
    def from_env(cls, model: str, **overrides: Any) -> "OpenRouterSettings":
        return cls(
            model=model,
            api_key=os.environ.get("AUTHCOMM_OPENROUTER_API_KEY", ""),
            base_url=os.environ.get(
                "AUTHCOMM_OPENROUTER_BASE_URL", DEFAULT_BASE_URL
            ),
            **overrides,
        )


@dataclass(frozen=True)
class ModelTurn:
    response_id: str | None
    requested_model: str
    returned_model: str | None
    served_endpoint_model: str | None
    provider: str | None
    latency_s: float
    output_text: str
    output_items: list[dict[str, Any]]
    usage: dict[str, Any]
    openrouter_metadata: dict[str, Any]
    request_parameters: dict[str, Any]
    request_started_monotonic_s: float | None = None
    response_completed_monotonic_s: float | None = None
    response_status: str | None = "completed"
    incomplete_details: Any = None
    response_error: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_completed_response(turn: ModelTurn) -> None:
    """Reject provider-side incomplete or failed responses before tool parsing."""
    if (turn.response_status == "completed"
            and turn.incomplete_details in (None, {}, [])
            and turn.response_error in (None, {}, [])):
        return
    detail = {
        "response_status": turn.response_status,
        "incomplete_details": turn.incomplete_details,
        "response_error": turn.response_error,
    }
    error = ProviderResponseError(
        "provider response was not complete: "
        + json.dumps(detail, sort_keys=True, ensure_ascii=False))
    error.model_turn = turn
    raise error


class OpenRouterResponsesClient:
    """Small injectable client used by the live runner and offline tests."""

    def __init__(self, settings: OpenRouterSettings, client: Any | None = None):
        self.settings = settings
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=settings.api_key,
                base_url=settings.base_url,
                timeout=settings.timeout_s,
                max_retries=0,
                default_headers={"X-OpenRouter-Metadata": "enabled"},
            )
        self._client = client

    def _provider_request(self) -> dict[str, Any]:
        provider: dict[str, Any] = {
            "allow_fallbacks": False,
            "require_parameters": True,
        }
        if self.settings.provider_order:
            provider["order"] = list(self.settings.provider_order)
        return provider

    async def create_response(
        self,
        *,
        input_items: str | Sequence[Mapping[str, Any]],
        instructions: str | None = None,
        tools: Sequence[Mapping[str, Any]] = (),
        metadata: Mapping[str, str] | None = None,
        previous_response_id: str | None = None,
        session_id: str | None = None,
    ) -> ModelTurn:
        extra_body: dict[str, Any] = {"provider": self._provider_request()}
        if session_id:
            extra_body["session_id"] = session_id

        kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "input": input_items,
            "max_output_tokens": self.settings.max_output_tokens,
            "reasoning": {"effort": self.settings.reasoning_effort},
            "store": False,
            "extra_body": extra_body,
        }
        if tools:
            kwargs["tools"] = list(tools)
            kwargs["tool_choice"] = "required"
        if instructions:
            kwargs["instructions"] = instructions
        if metadata:
            kwargs["metadata"] = dict(metadata)
        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id
        if self.settings.temperature is not None:
            kwargs["temperature"] = self.settings.temperature

        started = monotonic()
        response = await self._client.responses.create(**kwargs)
        completed = monotonic()
        latency_s = completed - started

        model_extra = _plain(_get(response, "model_extra", {})) or {}
        router_metadata = model_extra.get("openrouter_metadata", {})
        if not isinstance(router_metadata, dict):
            router_metadata = {"raw": router_metadata}

        output_items = _plain(_get(response, "output", []))
        if not isinstance(output_items, list):
            output_items = [output_items]

        returned_model = _get(response, "model")
        selected_endpoint = next((
            endpoint
            for endpoint in router_metadata.get("endpoints", {}).get("available", [])
            if isinstance(endpoint, dict) and endpoint.get("selected") is True
        ), {})
        provider = router_metadata.get("provider") or selected_endpoint.get("provider")
        served_endpoint_model = selected_endpoint.get("model") or returned_model
        usage = _plain(_get(response, "usage", {})) or {}
        if not isinstance(usage, dict):
            usage = {"raw": usage}
        if not isinstance(usage.get("cost"), (int, float)):
            metadata_cost = router_metadata.get("cost")
            if not isinstance(metadata_cost, (int, float)):
                metadata_cost = model_extra.get("cost")
            usage["cost"] = (
                metadata_cost
                if isinstance(metadata_cost, (int, float))
                and not isinstance(metadata_cost, bool)
                else None
            )

        request_parameters = {
            "reasoning_effort": self.settings.reasoning_effort,
            "temperature": self.settings.temperature,
            "max_output_tokens": self.settings.max_output_tokens,
            "provider": self._provider_request(),
            "session_id_present": bool(session_id),
            "continued_response": bool(previous_response_id),
            "stateless_history_items": (
                len(input_items) if not isinstance(input_items, str) else 0),
            "tool_count": len(tools),
        }
        return ModelTurn(
            response_id=_get(response, "id"),
            requested_model=self.settings.model,
            returned_model=returned_model,
            served_endpoint_model=served_endpoint_model,
            provider=provider,
            latency_s=latency_s,
            output_text=_get(response, "output_text", "") or "",
            output_items=output_items,
            usage=usage,
            openrouter_metadata=router_metadata,
            request_parameters=request_parameters,
            request_started_monotonic_s=started,
            response_completed_monotonic_s=completed,
            response_status=_get(response, "status"),
            incomplete_details=_plain(_get(response, "incomplete_details")),
            response_error=_plain(_get(response, "error")),
        )


class RetryingResponsesClient:
    """Retry only one failed API request while retaining all prior cell state."""

    def __init__(self, client: Any, max_retries: int = 2,
                 backoff_s: Sequence[float] = (2.0, 5.0)):
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self.client = client
        self.settings = getattr(client, "settings", None)
        self.max_retries = int(max_retries)
        self.backoff_s = tuple(float(value) for value in backoff_s)
        self.total_attempts = 0
        self.retry_count = 0
        self.total_retry_wait_s = 0.0
        self.error_log: list[dict[str, Any]] = []

    async def create_response(self, **kwargs: Any) -> ModelTurn:
        role = str((kwargs.get("metadata") or {}).get("role", "unknown"))
        turn = str((kwargs.get("metadata") or {}).get("turn", "unknown"))
        for retry_index in range(self.max_retries + 1):
            self.total_attempts += 1
            started = monotonic()
            try:
                return await self.client.create_response(**kwargs)
            except Exception as error:
                completed = monotonic()
                transient = is_transient_api_error(error)
                will_retry = transient and retry_index < self.max_retries
                retry_wait_s = 0.0
                if will_retry and self.backoff_s:
                    delay_index = min(
                        retry_index, len(self.backoff_s) - 1)
                    retry_wait_s = self.backoff_s[delay_index]
                self.error_log.append({
                    "api_attempt": self.total_attempts,
                    "role": role,
                    "turn": turn,
                    "retry_index": retry_index,
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                    "transient": transient,
                    "will_retry": will_retry,
                    "elapsed_s": completed - started,
                    "retry_wait_s": retry_wait_s,
                    "usage_known": False,
                    "input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": None,
                    "cost_usd": None,
                })
                if not transient:
                    raise
                if not will_retry:
                    exhausted = TransientRequestRetriesExhausted(
                        f"temporary API failure persisted after "
                        f"{self.max_retries} retries: {error}")
                    exhausted.request_error_log = list(self.error_log)
                    raise exhausted from error
                self.retry_count += 1
                if retry_wait_s:
                    wait_started = monotonic()
                    await asyncio.sleep(retry_wait_s)
                    actual_wait_s = monotonic() - wait_started
                    self.total_retry_wait_s += actual_wait_s
                    self.error_log[-1]["retry_wait_s"] = actual_wait_s

        raise AssertionError("unreachable")


def write_turn(path: str, turn: ModelTurn) -> None:
    """Write one turn atomically enough for append-free per-request logs."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(turn.to_dict(), handle, indent=2, ensure_ascii=False)
        handle.write("\n")
