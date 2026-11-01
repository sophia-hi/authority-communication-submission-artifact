"""Live execution of one experimental cell through the recorded protocol.

This module contains organizational orchestration. Batch entry points require
an explicit --execute-live flag before making paid requests.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
import hashlib
import json
from time import monotonic
from typing import Any, Mapping

from calculate import CALCULATOR_TOOL, evaluate_batch
from data_schema import DATA_SCHEMA_VERSION
from agent_interface import (
    AgentInterfaceError, ParsedToolCall, agent_facing_role_name, initial_task,
    parse_single_tool_call, role_dossier, system_instructions, tool_schemas,
)
from failure_policy import classify_failure
from openrouter_client import (ModelTurn, OpenRouterResponsesClient,
                               ProviderResponseError, RetryingResponsesClient,
                               TransientRequestRetriesExhausted,
                               validate_completed_response)
from organizations import BRANCH_SPECIALIST_ROLE_BRANCH, SPECS
from protocol import (COMMUNICATING_ORGANIZATIONS, PROTOCOL_VERSION,
                      ProtocolError, ProtocolState)
from reconstruction import score_reconstruction
from scoring import score_organizational_failure, score_plan


class LiveCellError(RuntimeError):
    pass


class LiveCellInfrastructureError(RuntimeError):
    pass


class ModelOutputLimitError(LiveCellError):
    """The frozen model used its output allowance without a legal action."""


class ModelContextLengthError(LiveCellError):
    """The frozen model/request exceeded the available context."""


class ModelResponseFilteredError(LiveCellError):
    """The frozen response was blocked by a content filter."""


class ProviderIncompleteResponseError(RuntimeError):
    """An unexplained incomplete response requires human inspection."""


class EmergencyGuardError(LiveCellError):
    """An emergency engineering guard stopped a nonterminating trajectory."""


@dataclass
class RoleSession:
    organization: str
    role: str
    branch_index: int | None
    instructions: str
    dossier: str
    previous_response_id: str | None = None
    pending_call_id: str | None = None
    pending_call_name: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    turn_number: int = 0
    done: bool = False
    inbox: list[str] = field(default_factory=list)
    pending_delivery_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class RoleAction:
    role: str
    call: ParsedToolCall
    turn: ModelTurn
    completed_at_s: float
    request_integrity: dict[str, Any]
    request_timing: dict[str, float]
    request_context: dict[str, Any] | None
    applied_before_return: bool = False


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _session(family: dict, rho: float, organization: str,
             role: str) -> RoleSession:
    index = None
    if role == "Lead":
        index = family["lead_branch_index"]
    elif role == "Reporting":
        index = family["reporting_branch_index"]
    elif (organization in {"independent", "mutual"}
          and role in BRANCH_SPECIALIST_ROLE_BRANCH):
        index = BRANCH_SPECIALIST_ROLE_BRANCH[role]
    return RoleSession(
        organization=organization,
        role=role,
        branch_index=index,
        instructions=system_instructions(organization, role, index),
        dossier=role_dossier(family, rho, organization, role),
    )


def _continuation_output(action_name: str, inbox: list[str],
                         allowed: set[str]) -> str:
    lines = [f"Your {action_name} call was accepted."]
    if inbox:
        lines.append("New protocol information:")
        lines.extend(inbox)
    lines.append("Currently allowed tools: " + ", ".join(sorted(allowed)))
    lines.append("Continue your analysis and call exactly one allowed tool.")
    return "\n".join(lines)


def _message_delivery_text(sender: str, text: str, *,
                           opening: bool = False,
                           same_round_filing: bool = False) -> str:
    prefix = "Mandatory opening communication delivered.\n" if opening else ""
    if same_round_filing:
        prefix += (
            "This message was sent in the same round as your filing. It was "
            "not read before that decision and cannot change it.\n")
    return prefix + f"{sender} message: {text}"


def _committed_handoff_delivery_text(action: str, text: str) -> str:
    return (
        f"Mandatory opening communication delivered.\n"
        f"Reporting Specialist committed action: {action}\n"
        f"Reporting Specialist message:\n{text}"
    )


def _report_delivery_text(text: str, sender: str = "Reporting") -> str:
    return _message_delivery_text(sender, text, opening=True)


def _submission_notice_text(submitter: str,
                            communication_remains_open: bool = True) -> str:
    ending = (
        "Filing the decision did not end communication."
        if communication_remains_open else
        "The one-way communication channel is now closed."
    )
    return (
        f"{submitter} has filed an irreversible branch decision. The action "
        f"was not revealed. {ending}"
    )


def _decline_notice_text(actor: str) -> str:
    return (
        f"{actor} declined to take a communication action in this round."
    )


def _finish_notice_text(actor: str, organization: str) -> str:
    return (
        f"{actor} permanently closed the communication channel. Finishing "
        "communication did not submit any decision. Any unsubmitted decision "
        "will be handled separately in the final-decision stage."
    )


def _final_decision_notice_text() -> str:
    return (
        "Each communication participant reached three consecutive decline/pass "
        "opportunities without substantive progress. "
        "Communication is now closed and the protocol has entered the final "
        "decision phase. No decision was chosen for you. Use your remaining "
        "submission tool to make any final decision you hold."
    )


def _calculator_continuation_output(result: dict[str, Any],
                                    allowed: set[str]) -> str:
    return json.dumps(
        {
            "calculator": result,
            "notice": (
                "This was a private internal calculation. No message was sent, "
                "no decision was submitted, and the current organizational turn "
                "remains open."
            ),
            "currently_allowed_tools": sorted(allowed),
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )


def agent_facing_runtime_examples() -> list[dict[str, str]]:
    """Complete catalog of runtime text templates generated by the live runner."""
    allowed = {"decline_message", "finish_communication", "send_message"}
    calculator_result = evaluate_batch(["2 + 3 * 4"])
    return [
        {
            "name": "accepted action with a newly delivered message",
            "text": _continuation_output(
                "send_message",
                [_message_delivery_text("Counterpart", "example message")],
                allowed,
            ),
        },
        {
            "name": "free-form message delivery",
            "text": _message_delivery_text(
                "Branch 1 Specialist", "example message"),
        },
        {
            "name": "two-way opening delivery",
            "text": _message_delivery_text(
                "Branch 1 Specialist", "example opening", opening=True),
        },
        {
            "name": "message sent in the same round as filing",
            "text": _message_delivery_text(
                "Counterpart", "example message", same_round_filing=True),
        },
        {
            "name": "Committed Handoff delivery",
            "text": _committed_handoff_delivery_text(
                "A", "example handoff message"),
        },
        {
            "name": "Reporting first-message delivery",
            "text": _report_delivery_text("example report"),
        },
        {
            "name": "Mutual partner submission notice",
            "text": _submission_notice_text("Branch 1 Specialist"),
        },
        {
            "name": "one-way channel closed after receiver filing",
            "text": _submission_notice_text(
                "Receiving Specialist", communication_remains_open=False),
        },
        {
            "name": "one-turn decline notice",
            "text": _decline_notice_text("Branch 2 Specialist"),
        },
        {
            "name": "Mutual communication-finished notice",
            "text": _finish_notice_text("Branch 2 Specialist", "mutual"),
        },
        {
            "name": "Centralized Two-way communication-finished notice",
            "text": _finish_notice_text("Reporting", "centralized_two_way"),
        },
        {
            "name": "final-decision-phase notice after three empty rounds",
            "text": _final_decision_notice_text(),
        },
        {
            "name": "private calculator tool result",
            "text": _calculator_continuation_output(
                calculator_result, {"send_message", "submit_branch", CALCULATOR_TOOL}),
        },
    ]


async def _act(client: OpenRouterResponsesClient, session: RoleSession,
               allowed: set[str], run_id: str, started: float,
               queued_monotonic_s: float,
               initial_context: str = "",
               continuation_output: str | None = None,
               capture_request_text: bool = False,
               expected_requested_model: str | None = None,
               expected_served_endpoint_model: str | None = None,
               expected_provider: str | None = None) -> RoleAction:
    if not allowed:
        raise LiveCellError(f"{session.role} has no allowed action")
    session.turn_number += 1
    if session.previous_response_id is None:
        prompt = session.dossier + "\n\n# Assignment\n" + initial_task(
            session.organization, session.role)
        if initial_context:
            prompt += "\n\n# Protocol information already received\n" + initial_context
        input_items: Any = [{
            "role": "user",
            "content": [{"type": "input_text", "text": prompt}],
        }]
    else:
        if not session.pending_call_id:
            raise LiveCellError(f"{session.role} has no pending tool result")
        output = continuation_output
        if output is None:
            output = _continuation_output(
                session.pending_call_name or "previous", session.inbox, allowed)
        session.inbox.clear()
        input_items = [*session.history, {
            "type": "function_call_output",
            "call_id": session.pending_call_id,
            "output": output,
        }]
    tools = tool_schemas(allowed)
    metadata = {
        "run_id": run_id,
        "role": session.role,
        "turn": str(session.turn_number),
    }
    session_id = f"{run_id}:{session.role}"
    request_payload = {
        "instructions": session.instructions,
        "input_items": input_items,
        "tools": tools,
        "metadata": metadata,
        "session_id": session_id,
    }
    request_integrity = {
        "instructions_sha256": _sha256_text(session.instructions),
        "dossier_sha256": _sha256_text(session.dossier),
        "input_items_sha256": _sha256_json(input_items),
        "tools_sha256": _sha256_json(tools),
        "request_payload_sha256": _sha256_json(request_payload),
        "input_item_count": len(input_items),
    }
    request_context = (
        {"request_payload": request_payload}
        if capture_request_text else None
    )
    def matching_error_rows() -> list[dict[str, Any]]:
        return [
            row for row in getattr(client, "error_log", [])
            if row.get("role") == session.role
            and str(row.get("turn")) == str(session.turn_number)
        ]

    prior_errors = len(matching_error_rows())
    try:
        turn = await client.create_response(
            instructions=session.instructions,
            input_items=input_items,
            tools=tools,
            metadata=metadata,
            session_id=session_id,
        )
    except Exception as exc:
        request_errors = matching_error_rows()[prior_errors:]
        failed_request_s = sum(
            float(row.get("elapsed_s", 0.0)) for row in request_errors)
        retry_wait_s = sum(
            float(row.get("retry_wait_s", 0.0)) for row in request_errors)
        exc.request_integrity = request_integrity
        exc.request_context = request_context
        exc.request_timing = {
            "queue_entered_at_s": queued_monotonic_s - started,
            "request_failed_at_s": monotonic() - started,
            "failed_request_time_s": failed_request_s,
            "retry_wait_s": retry_wait_s,
            "queue_delay_s": max(
                0.0, monotonic() - queued_monotonic_s
                - failed_request_s - retry_wait_s),
        }
        raise
    response_completed = (
        turn.response_completed_monotonic_s
        if turn.response_completed_monotonic_s is not None else monotonic())
    request_started = (
        turn.request_started_monotonic_s
        if turn.request_started_monotonic_s is not None
        else response_completed - turn.latency_s)
    request_errors = matching_error_rows()[prior_errors:]
    failed_request_s = sum(
        float(row.get("elapsed_s", 0.0)) for row in request_errors)
    retry_wait_s = sum(
        float(row.get("retry_wait_s", 0.0)) for row in request_errors)
    request_timing = {
        "queue_entered_at_s": queued_monotonic_s - started,
        "request_started_at_s": request_started - started,
        "response_completed_at_s": response_completed - started,
        "queue_delay_s": max(
            0.0, request_started - queued_monotonic_s
            - failed_request_s - retry_wait_s),
        "provider_latency_s": turn.latency_s,
        "failed_request_time_s": failed_request_s,
        "retry_wait_s": retry_wait_s,
    }
    try:
        validate_completed_response(turn)
        if (not isinstance(turn.response_id, str)
                or not turn.response_id.strip()):
            raise LiveCellInfrastructureError(
                "completed provider response is missing its response id")
        if (expected_requested_model and turn.returned_model
                and turn.returned_model != expected_requested_model):
            raise LiveCellInfrastructureError(
                "returned model differs from the requested frozen model: "
                f"{turn.returned_model!r} != {expected_requested_model!r}")
        if (expected_served_endpoint_model
                and turn.served_endpoint_model
                != expected_served_endpoint_model):
            raise LiveCellInfrastructureError(
                "served endpoint model differs from the frozen snapshot: "
                f"{turn.served_endpoint_model!r} != "
                f"{expected_served_endpoint_model!r}")
        if expected_provider and turn.provider != expected_provider:
            raise LiveCellInfrastructureError(
                "response provider differs from the frozen provider: "
                f"{turn.provider!r} != {expected_provider!r}")
    except ProviderResponseError as exc:
        details = turn.incomplete_details
        reason = (details.get("reason") if isinstance(details, Mapping)
                  else None)
        if (turn.response_status == "incomplete"
                and reason in {"max_output_tokens", "output_limit", "length"}):
            terminal = ModelOutputLimitError(
                "model response reached max_output_tokens before a legal action")
            terminal.model_turn = turn
            terminal.completed_at_s = monotonic() - started
            terminal.request_integrity = request_integrity
            terminal.request_context = request_context
            terminal.request_timing = request_timing
            raise terminal from exc
        if (turn.response_status == "incomplete"
                and reason in {"context_length_exceeded",
                               "context_window_exceeded"}):
            terminal = ModelContextLengthError(
                "model response exceeded the available context length")
            terminal.model_turn = turn
            terminal.completed_at_s = monotonic() - started
            terminal.request_integrity = request_integrity
            terminal.request_context = request_context
            terminal.request_timing = request_timing
            raise terminal from exc
        category = (ModelResponseFilteredError
                    if reason == "content_filter"
                    else ProviderIncompleteResponseError)
        failure = category(str(exc))
        failure.model_turn = turn
        failure.completed_at_s = monotonic() - started
        failure.request_integrity = request_integrity
        failure.request_context = request_context
        failure.request_timing = request_timing
        raise failure from exc
    except LiveCellInfrastructureError as exc:
        exc.model_turn = turn
        exc.completed_at_s = monotonic() - started
        exc.request_integrity = request_integrity
        exc.request_context = request_context
        exc.request_timing = request_timing
        raise
    try:
        call = parse_single_tool_call(turn.output_items, allowed)
    except AgentInterfaceError as exc:
        exc.model_turn = turn
        exc.completed_at_s = monotonic() - started
        exc.request_integrity = request_integrity
        exc.request_context = request_context
        exc.request_timing = request_timing
        raise
    session.previous_response_id = turn.response_id
    session.pending_call_id = call.call_id
    session.pending_call_name = call.name
    session.history = [*input_items, *turn.output_items]
    return RoleAction(
        session.role, call, turn, monotonic() - started,
        request_integrity, request_timing, request_context)


def _apply(state: ProtocolState, action: RoleAction) -> str | None:
    role, call, args = action.role, action.call, action.call.arguments
    try:
        if call.name == "submit_company":
            state.submit_company(role, args["branch1"], args["branch2"])
            return None
        if call.name == "submit_branch":
            state.submit_branch(role, args["action"])
            return None
        if call.name == "send_report":
            report = args["text"]
            state.send_report(role, report)
            return report
        if call.name == "commit_and_handoff":
            report = args["text"]
            state.commit_and_handoff(role, args["action"], report)
            return report
        if call.name == "send_message":
            state.send_message(role, args["text"])
            return args["text"]
    except KeyError as exc:
        raise AgentInterfaceError(
            f"tool {call.name!r} is missing required argument {exc.args[0]!r}") from exc
    if call.name == "decline_message":
        state.decline_message(role)
        return None
    if call.name == "finish_communication":
        state.finish_communication(role)
        return None
    if call.name in {"wait_for_report"}:
        return None
    raise LiveCellError(f"unhandled tool {call.name}")


async def _gather_actions(*awaitables: Any,
                          partial_state: ProtocolState | None = None,
                          terminal_success_is_sufficient: bool = False,
                          ) -> list[RoleAction]:
    """Finish a parallel batch and preserve valid actions if its peer fails."""
    tasks = [asyncio.create_task(awaitable) for awaitable in awaitables]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)
    actions = [outcome for outcome in outcomes
               if isinstance(outcome, RoleAction)]
    errors = [outcome for outcome in outcomes
              if isinstance(outcome, BaseException)]
    if errors:
        if partial_state is not None:
            for action in sorted(actions, key=lambda item: item.completed_at_s):
                _apply(partial_state, action)
            if terminal_success_is_sufficient and partial_state.terminal:
                # The failed peer request cannot invalidate a company plan that
                # was already completed by a valid concurrent action. The
                # failed request remains in the turn and request-error logs.
                return [replace(action, applied_before_return=True)
                        for action in actions]
        def error_priority(error: BaseException) -> tuple[int, int, str]:
            disposition = classify_failure(error)
            treatment_rank = {
                "stop_and_inspect": 0,
                "organizational_terminal": 1,
                "inspection_required": 2,
            }.get(disposition.treatment, 3)
            category_rank = {
                "output_limit_cutoff": 0,
                "context_length_exhaustion": 1,
                "invalid_model_action": 2,
                "emergency_guard_exhaustion": 3,
                "provider_network_failure": 4,
                "credential_failure": 5,
                "billing_credit_failure": 6,
                "model_route_unavailable": 7,
                "process_interruption": 8,
                "unexpected_exception": 9,
            }.get(disposition.category, 10)
            return treatment_rank, category_rank, disposition.category

        selected_error = sorted(errors, key=error_priority)[0]
        selected_error.parallel_successful_actions = [
            {
                "role": action.role,
                "tool": action.call.name,
                "arguments": action.call.arguments,
                "completed_at_s": action.completed_at_s,
            }
            for action in actions
        ]
        selected_error.parallel_failures = [
            {
                "failure_category": classify_failure(error).category,
                "failure_type": type(error).__name__,
                "failure_message": str(error),
            }
            for error in sorted(errors, key=error_priority)
        ]
        raise selected_error
    return actions


class CellExecutor:
    def __init__(self, client: OpenRouterResponsesClient,
                 emergency_max_model_requests: int = 160,
                 emergency_max_messages: int = 40,
                 expected_served_endpoint_model: str | None = None,
                 expected_provider: str | None = None,
                 capture_request_text: bool = False,
                 transient_request_retries: int = 2,
                 transient_retry_backoff_s: tuple[float, ...] = (2.0, 5.0),
                 consecutive_empty_round_limit: int = 3):
        if consecutive_empty_round_limit < 1:
            raise ValueError(
                "consecutive_empty_round_limit must be positive")
        self.client = RetryingResponsesClient(
            client, max_retries=transient_request_retries,
            backoff_s=transient_retry_backoff_s)
        self.max_requests = emergency_max_model_requests
        self.max_messages = emergency_max_messages
        self.expected_served_endpoint_model = expected_served_endpoint_model
        self.expected_provider = expected_provider
        self.capture_request_text = capture_request_text
        self.consecutive_empty_round_limit = consecutive_empty_round_limit
        self.turn_log: list[dict[str, Any]] = []
        self.unapplied_calls: list[dict[str, Any]] = []
        self.delivery_log: list[dict[str, Any]] = []
        self.calculator_log: list[dict[str, Any]] = []
        self.prompt_integrity: dict[str, dict[str, str]] = {}
        self.logical_request_count = 0
        self.started = 0.0
        self.run_id = ""
        self.state: ProtocolState | None = None

    @property
    def request_count(self) -> int:
        """Number of API attempts, including request-level retries."""
        return self.client.total_attempts

    def accepted_branch_actions(self) -> dict[str, str]:
        """Return every branch action that actually entered protocol state."""
        state = self.state
        if state is None:
            return {}
        if state.company_actions is not None:
            return {
                "1": state.company_actions[0],
                "2": state.company_actions[1],
            }
        return {
            str(index + 1): action
            for index, action in sorted(state.branch_actions.items())
        }

    def submission_audit(self) -> dict[str, list[dict[str, Any]]]:
        """Separate attempted, accepted, and unapplied final-decision calls."""
        submission_tools = {
            "submit_company", "submit_branch", "commit_and_handoff",
        }
        attempted = []
        for turn in self.turn_log:
            call = turn.get("tool_call")
            if (not isinstance(call, Mapping)
                    or call.get("name") not in submission_tools):
                continue
            attempted.append({
                "role": turn.get("role"),
                "turn_number": turn.get("turn_number"),
                "tool": call.get("name"),
                "arguments": call.get("arguments"),
                "completed_at_s": turn.get("completed_at_s"),
            })
        accepted = []
        event_to_tool = {
            "submit_company": "submit_company",
            "submit_branch": "submit_branch",
            "committed_handoff": "commit_and_handoff",
        }
        for event in (self.state.events if self.state else []):
            tool = event_to_tool.get(event.kind)
            if tool is None:
                continue
            accepted.append({
                "sequence": event.sequence,
                "role": event.actor,
                "tool": tool,
                "arguments": event.payload,
            })
        unapplied = [
            {
                "role": row.get("role"),
                "tool": row.get("tool"),
                "arguments": row.get("arguments"),
                "completed_at_s": row.get("completed_at_s"),
                "reason": row.get("reason"),
            }
            for row in self.unapplied_calls
            if row.get("tool") in submission_tools
        ]
        return {
            "attempted": attempted,
            "accepted": accepted,
            "unapplied": unapplied,
        }

    def process_summary(self) -> dict[str, Any]:
        """Return simple protocol counters without interpreting mechanisms."""
        state = self.state
        events = state.events if state else []
        is_communicating = bool(
            state and state.organization in COMMUNICATING_ORGANIZATIONS)
        communication_kinds = {"report", "message", "committed_handoff"}
        filing_kinds = {"submit_branch", "submit_company", "committed_handoff"}
        first_filing = next(
            (event.sequence for event in events if event.kind in filing_kinds),
            None,
        )
        messages_by_role: dict[str, int] = {}
        declines_by_role: dict[str, int] = {}
        finishes_by_role: dict[str, int] = {}
        automatic_closes_by_role: dict[str, int] = {}
        filed_round_by_role: dict[str, int] = {}
        for event in events:
            if event.kind in communication_kinds:
                messages_by_role[event.actor] = messages_by_role.get(event.actor, 0) + 1
            elif event.kind == "decline_message":
                declines_by_role[event.actor] = declines_by_role.get(event.actor, 0) + 1
            elif event.kind == "finish_communication":
                role = str(event.payload.get("role", event.actor))
                finishes_by_role[role] = finishes_by_role.get(role, 0) + 1
            elif event.kind == "auto_protocol_close":
                role = str(event.payload.get("role", event.actor))
                automatic_closes_by_role[role] = (
                    automatic_closes_by_role.get(role, 0) + 1)
            if event.kind in filing_kinds:
                filed_round_by_role[event.actor] = int(
                    event.payload.get("round_number", 0))
        rounds_by_role: dict[str, int] = {}
        wait_or_pass_turns: dict[str, int] = {}
        for turn in self.turn_log:
            role = str(turn.get("role"))
            round_number = turn.get("round_number")
            if isinstance(round_number, int) and round_number > 0:
                rounds_by_role[role] = max(rounds_by_role.get(role, 0), round_number)
            tool = (turn.get("tool_call") or {}).get("name")
            if tool in {"wait_for_report", "decline_message"}:
                wait_or_pass_turns[role] = wait_or_pass_turns.get(role, 0) + 1
        total_rounds = max(
            [0]
            + [int(turn.get("round_number", 0) or 0) for turn in self.turn_log]
            + [int(event.payload.get("round_number", 0) or 0) for event in events]
        ) if is_communicating else 0
        return {
            "total_communication_rounds": total_rounds,
            "rounds_by_role": dict(sorted(rounds_by_role.items())),
            "messages_sent_by_role": dict(sorted(messages_by_role.items())),
            "declines_by_role": dict(sorted(declines_by_role.items())),
            "finishes_by_role": dict(sorted(finishes_by_role.items())),
            "automatic_protocol_closes_by_role": dict(
                sorted(automatic_closes_by_role.items())),
            "wait_or_pass_turns_by_role": dict(
                sorted(wait_or_pass_turns.items())),
            "final_decision_filed_round_by_role": dict(
                sorted(filed_round_by_role.items())),
            "communication_close_reason": (
                state.communication_close_reason if state else None),
            "submit_only_final_decision_phase_entered": bool(
                state and state.final_decision_phase),
            "submit_only_phase_reason": (
                state.final_decision_phase_reason if state else None),
            "submit_only_phase_reason_code": (
                state.final_decision_phase_reason_code if state else None),
            "communication_continued_after_first_filing": bool(
                first_filing is not None and any(
                    event.sequence > first_filing
                    and event.kind in communication_kinds
                    for event in events
                )),
        }

    def _annotate_applied_action(
            self, action: RoleAction, state: ProtocolState, *,
            accepted: bool) -> None:
        """Complete process-state fields after protocol handling."""
        for turn in reversed(self.turn_log):
            call = turn.get("tool_call") or {}
            if (turn.get("role") == action.role
                    and call.get("name") == action.call.name
                    and turn.get("completed_at_s") == action.completed_at_s):
                turn["action_accepted"] = accepted
                turn["already_filed_after_turn"] = state.role_has_filed(
                    action.role)
                turn["communication_open_after_turn"] = (
                    state.communication_open)
                return

    def _deliver(self, recipient: RoleSession, sender: str, kind: str,
                 content: str, *,
                 same_round_with_submission: bool = False) -> None:
        delivery_id = len(self.delivery_log) + 1
        recipient.inbox.append(content)
        recipient.pending_delivery_ids.append(delivery_id)
        self.delivery_log.append({
            "delivery_id": delivery_id,
            "sender": sender,
            "recipient": recipient.role,
            "kind": kind,
            "content": content,
            "content_sha256": _sha256_text(content),
            "delivered_at_s": monotonic() - self.started,
            "read_at_turn": None,
            "read_at_s": None,
            "decision_delivery_status": "pending",
            "same_round_with_submission": same_round_with_submission,
        })

    def _finalize_unread_deliveries(self) -> None:
        for delivery in self.delivery_log:
            if delivery["decision_delivery_status"] == "pending":
                delivery["decision_delivery_status"] = "unread_channel_closed"

    def resource_summary(self, wall_time_s: float | None = None) -> dict[str, Any]:
        """Aggregate resources from every recorded model response in this attempt."""
        totals: dict[str, Any] = {
            "model_requests": self.request_count,
            "recorded_model_responses": 0,
            "request_retries": self.client.retry_count,
            "retry_wait_s": self.client.total_retry_wait_s,
            "failed_request_time_s": sum(
                float(row.get("elapsed_s", 0.0))
                for row in self.client.error_log),
            "requests_with_unknown_usage": len(self.client.error_log),
            "usage_complete": not self.client.error_log,
            "known_input_tokens": 0,
            "known_output_tokens": 0,
            "known_reasoning_tokens": 0,
            "known_total_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "provider_latency_s": 0.0,
            "queue_delay_s": 0.0,
            "known_cost_usd": 0.0,
            "requests_with_unknown_cost": len(self.client.error_log),
            "cost_complete": not self.client.error_log,
            "cost_usd": None,
            "calculator_calls": len(self.calculator_log),
            "calculator_expressions": sum(
                int(row.get("expression_count", 0))
                for row in self.calculator_log),
            "calculator_time_s": sum(
                float(row.get("duration_s", 0.0))
                for row in self.calculator_log),
        }
        role_active: dict[str, float] = {}
        role_queue: dict[str, float] = {}
        role_failed_request: dict[str, float] = {}
        role_retry_wait: dict[str, float] = {}
        intervals: dict[str, list[tuple[float, float]]] = {}
        token_fields_complete = {
            "input_tokens": not self.client.error_log,
            "output_tokens": not self.client.error_log,
            "total_tokens": not self.client.error_log,
            "reasoning_tokens": not self.client.error_log,
        }
        for turn in self.turn_log:
            model = turn.get("model")
            if not isinstance(model, dict):
                continue
            totals["recorded_model_responses"] += 1
            usage = model.get("usage")
            if not isinstance(usage, dict):
                usage = {}
            response_usage_known = True
            for field in ("input_tokens", "output_tokens", "total_tokens"):
                value = usage.get(field)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    totals[field] += value
                    totals[f"known_{field}"] += value
                else:
                    token_fields_complete[field] = False
                    response_usage_known = False
            details = usage.get("output_tokens_details")
            if isinstance(details, dict):
                value = details.get("reasoning_tokens")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    totals["reasoning_tokens"] += value
                    totals["known_reasoning_tokens"] += value
                else:
                    token_fields_complete["reasoning_tokens"] = False
            else:
                token_fields_complete["reasoning_tokens"] = False
            if not response_usage_known:
                totals["requests_with_unknown_usage"] += 1
                totals["usage_complete"] = False
            value = usage.get("cost")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals["known_cost_usd"] += value
            else:
                totals["requests_with_unknown_cost"] += 1
                totals["cost_complete"] = False
            value = model.get("latency_s")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals["provider_latency_s"] += value
                role = str(turn.get("role", "unknown"))
                role_active[role] = role_active.get(role, 0.0) + float(value)
            timing = turn.get("request_timing")
            if isinstance(timing, dict):
                role = str(turn.get("role", "unknown"))
                failed = timing.get("failed_request_time_s")
                if isinstance(failed, (int, float)) and not isinstance(failed, bool):
                    role_failed_request[role] = (
                        role_failed_request.get(role, 0.0) + float(failed))
                wait = timing.get("retry_wait_s")
                if isinstance(wait, (int, float)) and not isinstance(wait, bool):
                    role_retry_wait[role] = (
                        role_retry_wait.get(role, 0.0) + float(wait))
                delay = timing.get("queue_delay_s")
                if isinstance(delay, (int, float)) and not isinstance(delay, bool):
                    totals["queue_delay_s"] += delay
                    role = str(turn.get("role", "unknown"))
                    role_queue[role] = role_queue.get(role, 0.0) + float(delay)
                began = timing.get("request_started_at_s")
                ended = timing.get("response_completed_at_s")
                if (isinstance(began, (int, float))
                        and isinstance(ended, (int, float))):
                    intervals.setdefault(str(turn.get("role", "unknown")), []).append(
                        (float(began), float(ended)))
        state = self.state
        totals["communication_actions"] = sum(
            event.kind in {"request", "report", "message", "committed_handoff"}
            for event in (state.events if state else []))
        totals["wall_time_s"] = (
            monotonic() - self.started if wall_time_s is None else wall_time_s)
        overlap = 0.0
        roles = self.state.spec.initial_roles if self.state else ()
        left_role, right_role = roles if len(roles) == 2 else (None, None)
        for left in intervals.get(left_role, []):
            for right in intervals.get(right_role, []):
                overlap += max(0.0, min(left[1], right[1]) - max(left[0], right[0]))
        totals["parallel_overlap_s"] = overlap
        totals["role_active_time_s"] = dict(sorted(role_active.items()))
        totals["role_queue_delay_s"] = dict(sorted(role_queue.items()))
        totals["role_failed_request_time_s"] = dict(
            sorted(role_failed_request.items()))
        totals["role_retry_wait_s"] = dict(sorted(role_retry_wait.items()))
        for field, complete in token_fields_complete.items():
            if not complete:
                totals[field] = None
        if totals["cost_complete"]:
            totals["cost_usd"] = totals["known_cost_usd"]
        return totals

    def organizational_failure_result(
            self, family: dict, rho: float, organization: str, run_id: str,
            error: BaseException) -> dict[str, Any]:
        """Create an analyzable penalized result for a non-infrastructure failure."""
        elapsed = monotonic() - self.started
        for accepted in getattr(error, "parallel_successful_actions", []):
            if not isinstance(accepted, Mapping) or self.state is None:
                continue
            for turn in reversed(self.turn_log):
                call = turn.get("tool_call") or {}
                if (turn.get("role") == accepted.get("role")
                        and call.get("name") == accepted.get("tool")
                        and turn.get("completed_at_s")
                        == accepted.get("completed_at_s")):
                    turn["action_accepted"] = True
                    turn["already_filed_after_turn"] = (
                        self.state.role_has_filed(str(turn["role"])))
                    turn["communication_open_after_turn"] = (
                        self.state.communication_open)
                    break
        state = self.state
        partial = self.accepted_branch_actions()
        self._finalize_unread_deliveries()
        message = str(error)
        category = classify_failure(error).category
        scored = score_organizational_failure(family, rho)
        return {
            "run_id": run_id,
            "design_version": family["design_version"],
            "economic_generator_version": family["economic_generator_version"],
            "protocol_version": PROTOCOL_VERSION,
            "data_schema_version": DATA_SCHEMA_VERSION,
            "family_id": family["family_id"],
            "candidate_id": family["candidate_id"],
            "rho": rho,
            "organization": organization,
            "lead_branch_index": family["lead_branch_index"],
            "reporting_branch_index": family["reporting_branch_index"],
            "economic_family": family,
            "submitted": None,
            **scored,
            "failure_category": category,
            "failure_type": type(error).__name__,
            "failure_message": message,
            "parallel_failures": getattr(error, "parallel_failures", []),
            "partial_branch_actions": partial,
            "accepted_branch_actions": partial,
            "submission_audit": self.submission_audit(),
            "process_summary": self.process_summary(),
            "wall_time_s": elapsed,
            "model_requests": self.request_count,
            "resources": self.resource_summary(elapsed),
            "events": [event.__dict__ for event in (state.events if state else [])],
            "protocol_deliveries": self.delivery_log,
            "calculator_calls": self.calculator_log,
            "prompt_integrity": self.prompt_integrity,
            "turns": self.turn_log,
            "unapplied_calls": self.unapplied_calls,
            "request_errors": list(self.client.error_log),
            "emergency_guard_hit": category == "emergency_guard_exhaustion",
        }

    async def act(self, session: RoleSession, allowed: set[str],
                  initial_context: str = "", round_number: int = 0) -> RoleAction:
        self.prompt_integrity.setdefault(session.role, {
            "instructions_sha256": _sha256_text(session.instructions),
            "dossier_sha256": _sha256_text(session.dossier),
        })
        offered = set(allowed) | {CALCULATOR_TOOL}
        calculator_output: str | None = None
        while True:
            if self.logical_request_count >= self.max_requests:
                raise EmergencyGuardError("emergency model-request guard reached")
            self.logical_request_count += 1
            queued = monotonic()
            received_count = len(session.pending_delivery_ids)
            state = self.state
            already_filed = (
                state.role_has_filed(session.role) if state is not None else False)
            communication_open = (
                state.communication_open if state is not None else False)
            if session.pending_delivery_ids:
                read_at = queued - self.started
                for delivery_id in session.pending_delivery_ids:
                    delivery = self.delivery_log[delivery_id - 1]
                    delivery["read_at_turn"] = session.turn_number + 1
                    delivery["read_at_s"] = read_at
                    delivery["decision_delivery_status"] = (
                        "delivered_after_decision" if already_filed
                        else "delivered_before_decision")
                session.pending_delivery_ids.clear()
            try:
                action = await _act(
                    self.client, session, offered, self.run_id, self.started,
                    queued,
                    initial_context=initial_context,
                    continuation_output=calculator_output,
                    capture_request_text=self.capture_request_text,
                    expected_requested_model=getattr(
                        getattr(self.client, "settings", None), "model", None),
                    expected_served_endpoint_model=(
                        self.expected_served_endpoint_model),
                    expected_provider=self.expected_provider,
                )
            except AgentInterfaceError as exc:
                turn = getattr(exc, "model_turn", None)
                self.turn_log.append({
                    "role": session.role,
                    "round_number": round_number,
                    "turn_number": session.turn_number,
                    "action_type": None,
                    "message_sent": False,
                    "messages_received": received_count,
                    "already_filed_before_turn": already_filed,
                    "already_filed_after_turn": (
                        state.role_has_filed(session.role)
                        if state is not None else already_filed),
                    "communication_open_before_turn": communication_open,
            "communication_open_after_turn": (
                        state.communication_open
                        if state is not None else communication_open),
                    "protocol_tools": sorted(allowed),
                    "allowed_tools": sorted(offered),
                    "completed_at_s": getattr(exc, "completed_at_s", None),
                    "tool_call": None,
                    "parse_error": str(exc),
                    "model": turn.to_dict() if turn else None,
                    "request_integrity": getattr(exc, "request_integrity", None),
                    "request_timing": getattr(exc, "request_timing", None),
                    "request_context": getattr(exc, "request_context", None),
                })
                raise
            except Exception as exc:
                disposition = classify_failure(exc)
                if disposition.treatment == "organizational_terminal" \
                        and not isinstance(exc, LiveCellError):
                    wrapper_type = (
                        ModelContextLengthError
                        if disposition.category == "context_length_exhaustion"
                        else type(exc)
                    )
                    wrapped = wrapper_type(str(exc))
                    for name in (
                            "model_turn", "completed_at_s", "request_integrity",
                            "request_context", "request_timing"):
                        if hasattr(exc, name):
                            setattr(wrapped, name, getattr(exc, name))
                    exc = wrapped
                turn = getattr(exc, "model_turn", None)
                self.turn_log.append({
                    "role": session.role,
                    "round_number": round_number,
                    "turn_number": session.turn_number,
                    "action_type": None,
                    "message_sent": False,
                    "messages_received": received_count,
                    "already_filed_before_turn": already_filed,
                    "already_filed_after_turn": (
                        state.role_has_filed(session.role)
                        if state is not None else already_filed),
                    "communication_open_before_turn": communication_open,
                    "communication_open_after_turn": (
                        state.communication_open
                        if state is not None else communication_open),
                    "protocol_tools": sorted(allowed),
                    "allowed_tools": sorted(offered),
                    "completed_at_s": getattr(
                        exc, "completed_at_s", monotonic() - self.started),
                    "tool_call": None,
                    "request_error": str(exc),
                    "model": turn.to_dict() if turn else None,
                    "request_integrity": getattr(exc, "request_integrity", None),
                    "request_timing": getattr(exc, "request_timing", None),
                    "request_context": getattr(exc, "request_context", None),
                })
                raise exc
            turn_record = {
                "role": action.role,
                "round_number": round_number,
                "turn_number": session.turn_number,
                "action_type": action.call.name,
                "message_sent": action.call.name in {
                    "send_report", "send_message", "commit_and_handoff",
                },
                "messages_received": received_count,
                "already_filed_before_turn": already_filed,
                "already_filed_after_turn": already_filed,
                "communication_open_before_turn": communication_open,
                "communication_open_after_turn": communication_open,
                "protocol_tools": sorted(allowed),
                "allowed_tools": sorted(offered),
                "completed_at_s": action.completed_at_s,
                "tool_call": {
                    "name": action.call.name,
                    "arguments": action.call.arguments,
                },
                "model": action.turn.to_dict(),
                "request_integrity": action.request_integrity,
                "request_timing": action.request_timing,
                "request_context": action.request_context,
            }
            self.turn_log.append(turn_record)
            if action.call.name != CALCULATOR_TOOL:
                return action

            calc_started = monotonic()
            expressions = action.call.arguments.get("expressions")
            if (not isinstance(expressions, list)
                    or not expressions
                    or any(not isinstance(item, str) for item in expressions)):
                raise AgentInterfaceError(
                    "calculator expressions must be a nonempty array of strings")
            result = evaluate_batch(expressions)
            calc_completed = monotonic()
            calc_record = {
                "calculator_call_id": len(self.calculator_log) + 1,
                "role": session.role,
                "model_turn_number": session.turn_number,
                "input": {
                    "expressions": action.call.arguments.get("expressions"),
                },
                "output": result,
                "expression_count": int(result.get("n", 0)),
                "started_at_s": calc_started - self.started,
                "completed_at_s": calc_completed - self.started,
                "duration_s": calc_completed - calc_started,
            }
            self.calculator_log.append(calc_record)
            turn_record["calculator_result"] = result
            calculator_output = _calculator_continuation_output(result, offered)
            initial_context = ""

    async def run(self, family: dict, rho: float, organization: str,
                  run_id: str) -> dict[str, Any]:
        self.started = monotonic()
        self.run_id = run_id
        self.turn_log = []
        self.unapplied_calls = []
        self.delivery_log = []
        self.calculator_log = []
        self.prompt_integrity = {}
        self.logical_request_count = 0
        self.client.total_attempts = 0
        self.client.retry_count = 0
        self.client.total_retry_wait_s = 0.0
        self.client.error_log = []
        self.state = None
        state = ProtocolState(organization, family["lead_branch_index"])
        self.state = state

        if organization == "single":
            owner = _session(family, rho, organization, "Owner")
            state.current_round = 1
            action = await self.act(
                owner, {"submit_company"}, round_number=1)
            _apply(state, action)
            self._annotate_applied_action(action, state, accepted=True)

        elif organization == "independent":
            branch_1 = _session(
                family, rho, organization, "Branch 1 Specialist")
            branch_2 = _session(
                family, rho, organization, "Branch 2 Specialist")
            state.current_round = 1
            actions = await _gather_actions(
                self.act(branch_1, {"submit_branch"}, round_number=1),
                self.act(branch_2, {"submit_branch"}, round_number=1),
                partial_state=state,
            )
            for action in sorted(actions, key=lambda x: x.completed_at_s):
                _apply(state, action)
                self._annotate_applied_action(action, state, accepted=True)

        elif organization == "committed_handoff":
            lead = _session(family, rho, organization, "Lead")
            reporting = _session(family, rho, organization, "Reporting")
            state.current_round = 1
            first = await _gather_actions(
                self.act(lead, {"wait_for_report"}, round_number=1),
                self.act(reporting, {"commit_and_handoff"}, round_number=1),
                partial_state=state,
            )
            committed_action = ""
            handoff_message = ""
            for action in sorted(first, key=lambda x: x.completed_at_s):
                if (action.call.name == "commit_and_handoff"
                        and self.max_messages < 1):
                    raise EmergencyGuardError("emergency message guard reached")
                value = _apply(state, action)
                self._annotate_applied_action(action, state, accepted=True)
                if action.call.name == "commit_and_handoff":
                    committed_action = action.call.arguments["action"]
                    handoff_message = value or ""
            handoff = _committed_handoff_delivery_text(
                committed_action, handoff_message)
            self._deliver(
                lead, "Reporting", "committed_handoff",
                handoff)
            await self._run_open_exchange(
                state, family, rho, organization,
                sessions={"Lead": lead, "Reporting": reporting},
                message_count=1,
                start_round=2,
            )

        elif organization == "informational_handoff":
            lead = _session(family, rho, organization, "Lead")
            reporting = _session(family, rho, organization, "Reporting")
            state.current_round = 1
            first = await _gather_actions(
                self.act(lead, {"wait_for_report"}, round_number=1),
                self.act(reporting, {"send_report"}, round_number=1),
                partial_state=state,
            )
            report = ""
            for action in sorted(first, key=lambda x: x.completed_at_s):
                if (action.call.name == "send_report"
                        and self.max_messages < 1):
                    raise EmergencyGuardError("emergency message guard reached")
                value = _apply(state, action)
                self._annotate_applied_action(action, state, accepted=True)
                if action.call.name == "send_report":
                    report = value or ""
            self._deliver(
                lead, "Reporting", "report", _report_delivery_text(
                    report, agent_facing_role_name(
                        organization, "Reporting")))
            await self._run_open_exchange(
                state, family, rho, organization,
                sessions={"Lead": lead, "Reporting": reporting},
                message_count=1,
                start_round=2,
            )

        elif organization == "specialist_proactive":
            lead = _session(family, rho, organization, "Lead")
            reporting = _session(family, rho, organization, "Reporting")
            state.current_round = 1
            first = await _gather_actions(
                self.act(lead, {"wait_for_report"}, round_number=1),
                self.act(reporting, {"send_report"}, round_number=1),
                partial_state=state,
            )
            report = ""
            for action in sorted(first, key=lambda x: x.completed_at_s):
                if (action.call.name == "send_report"
                        and self.max_messages < 1):
                    raise EmergencyGuardError("emergency message guard reached")
                value = _apply(state, action)
                self._annotate_applied_action(action, state, accepted=True)
                if action.call.name == "send_report":
                    report = value or ""
            self._deliver(
                lead, "Reporting", "report", _report_delivery_text(report))
            await self._run_open_exchange(
                state, family, rho, organization,
                sessions={"Lead": lead, "Reporting": reporting},
                message_count=1,
                start_round=2,
            )

        elif organization in {"mutual", "centralized_two_way"}:
            await self._run_open_exchange(state, family, rho, organization)
        else:
            raise LiveCellError(f"unknown organization {organization}")

        plan = state.assembled_actions()
        if plan is None:
            raise LiveCellError("cell ended without a complete submission")
        self._finalize_unread_deliveries()
        elapsed = monotonic() - self.started
        scored = score_plan(family, rho, "".join(plan))
        reconstruction = score_reconstruction(family, rho, self.turn_log)
        resources = self.resource_summary(elapsed)
        return {
            "run_id": run_id,
            "design_version": family["design_version"],
            "economic_generator_version": family["economic_generator_version"],
            "protocol_version": PROTOCOL_VERSION,
            "data_schema_version": DATA_SCHEMA_VERSION,
            "family_id": family["family_id"],
            "candidate_id": family["candidate_id"],
            "rho": rho,
            "organization": organization,
            "lead_branch_index": family["lead_branch_index"],
            "reporting_branch_index": family["reporting_branch_index"],
            "economic_family": family,
            "submitted": "".join(plan),
            "accepted_branch_actions": self.accepted_branch_actions(),
            "submission_audit": self.submission_audit(),
            "process_summary": self.process_summary(),
            **scored,
            "reconstruction": reconstruction,
            "wall_time_s": elapsed,
            "model_requests": self.request_count,
            "resources": resources,
            "events": [event.__dict__ for event in state.events],
            "protocol_deliveries": self.delivery_log,
            "calculator_calls": self.calculator_log,
            "prompt_integrity": self.prompt_integrity,
            "turns": self.turn_log,
            "unapplied_calls": self.unapplied_calls,
            "request_errors": list(self.client.error_log),
            "emergency_guard_hit": False,
        }

    async def _run_open_exchange(
            self, state: ProtocolState, family: dict, rho: float,
            organization: str,
            sessions: dict[str, RoleSession] | None = None,
            message_count: int = 0,
            start_round: int = 1) -> None:
        roles = SPECS[organization].initial_roles
        if len(roles) != 2:
            raise LiveCellError("open exchange requires exactly two roles")
        counterpart = {roles[0]: roles[1], roles[1]: roles[0]}
        if sessions is None:
            sessions = {
                role: _session(family, rho, organization, role)
                for role in roles
            }
        no_progress_by_role = {role: 0 for role in roles}
        submission_notices_sent: set[str] = set()
        round_number = start_round

        while not state.terminal:
            state.current_round = round_number
            scheduled = {
                role: state.allowed_actions(role)
                for role in roles if state.allowed_actions(role)
            }
            # A finish-only action is a protocol transition, not a model choice.
            for role in list(scheduled):
                if scheduled[role] != {"finish_communication"}:
                    continue
                state.auto_finish_communication(
                    role, "finish was the only legal protocol action")
                sessions[role].done = True
                scheduled.pop(role)
            scheduled = {
                role: state.allowed_actions(role)
                for role in roles if state.allowed_actions(role)
            }
            if not scheduled:
                if state.terminal:
                    break
                raise LiveCellError("open exchange deadlocked before submission")

            scheduled_roles = list(scheduled)
            completed = await _gather_actions(*(
                    self.act(
                        sessions[role], scheduled[role],
                        round_number=round_number)
                    for role in scheduled_roles
                ), partial_state=state,
                terminal_success_is_sufficient=True,
            )

            for action in completed:
                if action.applied_before_return:
                    self._annotate_applied_action(
                        action, state, accepted=True)
            if state.terminal and any(
                    action.applied_before_return for action in completed):
                break

            accepted_names: dict[str, str] = {}
            role_order = {
                role: index for index, role in enumerate(scheduled_roles)}
            action_order = {
                "send_message": 0,
                "send_report": 0,
                "commit_and_handoff": 0,
                "decline_message": 0,
                "finish_communication": 1,
                "submit_branch": 2,
                "submit_company": 2,
            }
            # Apply by protocol semantics, never API completion order.
            completed = sorted(
                completed,
                key=lambda action: (
                    action_order.get(action.call.name, 1),
                    role_order[action.role],
                ),
            )
            submitting_roles = {
                action.role for action in completed
                if action.call.name in {"submit_branch", "submit_company"}
            }
            for action in completed:
                session = sessions[action.role]
                if state.terminal:
                    self.unapplied_calls.append({
                        "role": action.role,
                        "tool": action.call.name,
                        "arguments": action.call.arguments,
                        "completed_at_s": action.completed_at_s,
                        "reason": "another concurrent action made the cell terminal",
                    })
                    session.done = True
                    self._annotate_applied_action(
                        action, state, accepted=False)
                    continue
                if (action.call.name == "send_message"
                        and message_count >= self.max_messages):
                    raise EmergencyGuardError("emergency message guard reached")
                if (action.call.name == "finish_communication"
                        and "finish_communication" in scheduled[action.role]
                        and "finish_communication"
                        not in state.allowed_actions(action.role)):
                    state.finish_communication_preauthorized(action.role)
                    value = None
                else:
                    value = _apply(state, action)
                accepted_names[action.role] = action.call.name
                self._annotate_applied_action(
                    action, state, accepted=True)
                if action.call.name == "submit_company":
                    session.done = True
                elif action.call.name == "send_message":
                    message_count += 1
                    recipient = counterpart[action.role]
                    self._deliver(
                        sessions[recipient], action.role, "message",
                        _message_delivery_text(
                            agent_facing_role_name(organization, action.role),
                            value or "", opening=round_number == 1,
                            same_round_filing=(
                                recipient in submitting_roles)),
                        same_round_with_submission=(
                            recipient in submitting_roles))
                elif action.call.name == "decline_message":
                    recipient = counterpart[action.role]
                    self._deliver(
                        sessions[recipient], action.role, "protocol_notice",
                        _decline_notice_text(agent_facing_role_name(
                            organization, action.role)))
                elif action.call.name == "finish_communication":
                    if organization != "mutual":
                        session.done = True
                    recipient = counterpart[action.role]
                    self._deliver(
                        sessions[recipient], action.role, "protocol_notice",
                        _finish_notice_text(agent_facing_role_name(
                            organization, action.role), organization))

            for role, name in accepted_names.items():
                if name == "decline_message":
                    no_progress_by_role[role] += 1
                elif name == "send_message":
                    no_progress_by_role[role] = 0
                    no_progress_by_role[counterpart[role]] = 0
                else:
                    no_progress_by_role[role] = 0

            communication_roles = [
                role for role in roles
                if state.allowed_actions(role)
                & {"send_message", "decline_message", "finish_communication"}
            ]
            if (state.communication_open and communication_roles
                    and all(no_progress_by_role[role]
                            >= self.consecutive_empty_round_limit
                            for role in communication_roles)):
                state.enter_final_decision_phase(
                    "each communication participant reached three consecutive "
                    "decline/pass opportunities without substantive progress",
                    reason_code="per_agent_no_progress_limit",
                )
                for role, session in sessions.items():
                    if state.allowed_actions(role):
                        self._deliver(
                            session, "Protocol", "final_decision_phase",
                            _final_decision_notice_text())

            if state.terminal:
                break

            if organization in {"mutual", "informational_handoff"}:
                for role, session in sessions.items():
                    if (session.branch_index in state.branch_actions
                            and role not in submission_notices_sent):
                        recipient = counterpart[role]
                        communication_remains_open = not (
                            organization == "informational_handoff"
                            and role == "Lead")
                        self._deliver(
                            sessions[recipient], "Protocol", "submission_notice",
                            _submission_notice_text(
                                agent_facing_role_name(organization, role),
                                communication_remains_open))
                        submission_notices_sent.add(role)

            if (organization == "informational_handoff"
                    and state.lead_branch_index in state.branch_actions
                    and not state.terminal):
                state.enter_final_decision_phase(
                    "Receiving Specialist submitted; the one-way channel can no "
                    "longer affect an open receiver decision",
                    reason_code="receiver_decision_filed",
                )
            elif (state.communication_finished and not state.final_decision_phase
                  and not state.terminal):
                state.enter_final_decision_phase(
                    "a participant permanently finished communication",
                    reason_code="participant_finished_communication",
                )
            round_number += 1
