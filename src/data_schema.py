"""Machine-checkable schema for analyzable live cell records."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from scoring import score_organizational_failure, score_plan


DATA_SCHEMA_VERSION = "authority_communication_data_v9"
VERSION_IDENTITY_FIELDS = (
    "design_version", "economic_generator_version", "protocol_version",
    "data_schema_version",
)
RESOURCE_FIELDS = {
    "model_requests", "recorded_model_responses", "input_tokens",
    "output_tokens", "reasoning_tokens", "total_tokens",
    "known_input_tokens", "known_output_tokens", "known_reasoning_tokens",
    "known_total_tokens",
    "request_retries", "requests_with_unknown_usage", "usage_complete",
    "communication_actions", "provider_latency_s", "queue_delay_s",
    "retry_wait_s", "failed_request_time_s",
    "wall_time_s", "parallel_overlap_s", "cost_usd", "known_cost_usd",
    "requests_with_unknown_cost", "cost_complete",
    "role_active_time_s", "role_queue_delay_s",
    "role_failed_request_time_s", "role_retry_wait_s",
    "calculator_calls", "calculator_expressions", "calculator_time_s",
}
INTEGRITY_FIELDS = {
    "instructions_sha256", "dossier_sha256", "input_items_sha256",
    "tools_sha256", "request_payload_sha256", "input_item_count",
}
ECONOMIC_FAMILY_FIELDS = {
    "design_version", "economic_generator_version", "master_seed",
    "candidate_id", "rng_draws",
    "branch_primitives", "local", "interaction_primitives", "interaction",
    "utilities", "substantive_optima", "local_plan", "label_maps",
    "labeled_optima", "family_id", "lead_branch_index",
    "reporting_branch_index", "document_template_seed",
}
PROMPT_INTEGRITY_FIELDS = {"instructions_sha256", "dossier_sha256"}
COMPLETED_TIMING_FIELDS = {
    "queue_entered_at_s", "request_started_at_s",
    "response_completed_at_s", "queue_delay_s", "provider_latency_s",
}
FAILED_TIMING_FIELDS = {
    "queue_entered_at_s", "request_failed_at_s", "queue_delay_s",
    "failed_request_time_s", "retry_wait_s",
}


def _is_sha256(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _same_number(left: Any, right: Any, tolerance: float = 1e-9) -> bool:
    return (isinstance(left, (int, float)) and not isinstance(left, bool)
            and isinstance(right, (int, float)) and not isinstance(right, bool)
            and abs(float(left) - float(right)) <= tolerance)


class DataRecordError(ValueError):
    pass


def validate_version_identity(record: Mapping[str, Any],
                              expected: Mapping[str, Any],
                              label: str = "record") -> None:
    """Apply the same four-field frozen identity check at every gate."""
    mismatches = {
        field: {"record": record.get(field), "expected": expected.get(field)}
        for field in VERSION_IDENTITY_FIELDS
        if record.get(field) != expected.get(field)
    }
    if mismatches:
        raise DataRecordError(
            f"{label} version identity mismatch: "
            + json.dumps(mismatches, sort_keys=True))


def result_record_errors(result: Mapping[str, Any], status: str) -> list[str]:
    errors: list[str] = []
    required = {
        "run_id", "design_version", "economic_generator_version",
        "protocol_version",
        "data_schema_version", "family_id", "candidate_id", "rho",
        "organization", "lead_branch_index", "reporting_branch_index",
        "economic_family",
        "submitted", "exact_optimum", "raw_regret_m", "decision_score",
        "valid_submission", "organizational_failure", "failure_penalty",
        "penalty_is_scoring_convention", "resources", "events",
        "protocol_deliveries", "prompt_integrity", "turns",
        "unapplied_calls", "calculator_calls", "request_errors",
        "emergency_guard_hit", "accepted_branch_actions", "submission_audit",
        "process_summary",
    }
    errors.extend(f"missing result field: {name}"
                  for name in sorted(required - result.keys()))
    if result.get("data_schema_version") != DATA_SCHEMA_VERSION:
        errors.append("wrong data_schema_version")
    if result.get("protocol_version") != "communication_protocol_v21":
        errors.append("wrong protocol_version")
    resources = result.get("resources")
    if not isinstance(resources, Mapping):
        errors.append("resources must be an object")
    else:
        errors.extend(f"missing resource field: {name}"
                      for name in sorted(RESOURCE_FIELDS - resources.keys()))
        unknown_usage = resources.get("requests_with_unknown_usage")
        if (not isinstance(unknown_usage, int) or isinstance(unknown_usage, bool)
                or unknown_usage < 0):
            errors.append(
                "requests_with_unknown_usage must be a nonnegative integer")
        if unknown_usage:
            if resources.get("usage_complete") is not False:
                errors.append(
                    "usage_complete must be false when request usage is unknown")
            for field in ("input_tokens", "output_tokens", "reasoning_tokens",
                          "total_tokens"):
                if resources.get(field) is not None:
                    errors.append(
                        f"{field} must be null when aggregate usage is incomplete")
        elif unknown_usage == 0 and resources.get("usage_complete") is not True:
            errors.append("usage_complete must be true when all usage is known")
        for field in (
                "known_input_tokens", "known_output_tokens",
                "known_reasoning_tokens", "known_total_tokens"):
            value = resources.get(field)
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or value < 0):
                errors.append(f"{field} must be a nonnegative number")
        missing_cost = resources.get("requests_with_unknown_cost")
        if (not isinstance(missing_cost, int) or isinstance(missing_cost, bool)
                or missing_cost < 0):
            errors.append("requests_with_unknown_cost must be a nonnegative integer")
        known_cost = resources.get("known_cost_usd")
        if (not isinstance(known_cost, (int, float))
                or isinstance(known_cost, bool) or known_cost < 0):
            errors.append("known_cost_usd must be a nonnegative number")
        if isinstance(missing_cost, int) and not isinstance(missing_cost, bool):
            if missing_cost:
                if resources.get("cost_complete") is not False:
                    errors.append(
                        "cost_complete must be false when request cost is unknown")
                if resources.get("cost_usd") is not None:
                    errors.append("cost_usd must be null when any cost is unknown")
            else:
                if resources.get("cost_complete") is not True:
                    errors.append(
                        "cost_complete must be true when all costs are known")
                total_cost = resources.get("cost_usd")
                if (not isinstance(total_cost, (int, float))
                        or isinstance(total_cost, bool)):
                    errors.append("cost_usd must be numeric when cost is complete")
                elif (isinstance(known_cost, (int, float))
                      and abs(float(total_cost) - float(known_cost)) > 1e-12):
                    errors.append("cost_usd must equal known_cost_usd when complete")
    request_errors = result.get("request_errors")
    if not isinstance(request_errors, list):
        errors.append("request_errors must be a list")
    elif isinstance(resources, Mapping):
        if (not isinstance(resources.get("requests_with_unknown_usage"), int)
                or resources.get("requests_with_unknown_usage")
                < len(request_errors)):
            errors.append(
                "unknown-usage request count is smaller than request_errors")
        for index, request_error in enumerate(request_errors):
            if not isinstance(request_error, Mapping):
                errors.append(f"request error {index} must be an object")
                continue
            if request_error.get("usage_known") is not False:
                errors.append(
                    f"request error {index} must mark usage as unknown")
            for field in ("input_tokens", "output_tokens", "total_tokens",
                          "cost_usd"):
                if request_error.get(field) is not None:
                    errors.append(
                        f"request error {index} must store unknown {field} as null")
    economic_family = result.get("economic_family")
    if not isinstance(economic_family, Mapping):
        errors.append("economic_family must be an object")
    else:
        errors.extend(
            f"economic_family missing field: {name}"
            for name in sorted(ECONOMIC_FAMILY_FIELDS - economic_family.keys()))
        if "counterbalance_seed" not in economic_family:
            errors.append("economic_family missing field: counterbalance_seed")
        identity_checks = {
            "design_version": economic_family.get("design_version"),
            "economic_generator_version": economic_family.get(
                "economic_generator_version"),
            "family_id": economic_family.get("family_id"),
            "candidate_id": economic_family.get("candidate_id"),
            "lead_branch_index": economic_family.get("lead_branch_index"),
            "reporting_branch_index": economic_family.get(
                "reporting_branch_index"),
        }
        for field, expected in identity_checks.items():
            if result.get(field) != expected:
                errors.append(f"result {field} does not match economic_family")
    turns = result.get("turns")
    if not isinstance(turns, list):
        errors.append("turns must be a list")
    else:
        for index, turn in enumerate(turns):
            if not isinstance(turn, Mapping):
                errors.append(f"turn {index} must be an object")
                continue
            turn_required = {
                "role", "round_number", "turn_number", "action_type",
                "message_sent", "messages_received",
                "already_filed_before_turn", "already_filed_after_turn",
                "communication_open_before_turn",
                "communication_open_after_turn",
            }
            errors.extend(
                f"turn {index} missing process field: {name}"
                for name in sorted(turn_required - turn.keys()))
            integrity = turn.get("request_integrity")
            if not isinstance(integrity, Mapping):
                errors.append(f"turn {index} lacks request_integrity")
            else:
                missing = INTEGRITY_FIELDS - integrity.keys()
                errors.extend(
                    f"turn {index} missing integrity field: {name}"
                    for name in sorted(missing))
                for name in INTEGRITY_FIELDS - {"input_item_count"}:
                    if name in integrity and not _is_sha256(integrity[name]):
                        errors.append(
                            f"turn {index} integrity field is not SHA-256: {name}")
            timing = turn.get("request_timing")
            if not isinstance(timing, Mapping):
                errors.append(f"turn {index} lacks request_timing")
            else:
                model = turn.get("model")
                timing_fields = (COMPLETED_TIMING_FIELDS
                                 if isinstance(model, Mapping)
                                 else FAILED_TIMING_FIELDS)
                errors.extend(
                    f"turn {index} missing timing field: {name}"
                    for name in sorted(timing_fields - timing.keys()))
            context = turn.get("request_context")
            if context is not None:
                payload = (context.get("request_payload")
                           if isinstance(context, Mapping) else None)
                if not isinstance(payload, Mapping):
                    errors.append(
                        f"turn {index} request_context lacks request_payload")
                elif isinstance(integrity, Mapping):
                    checks = {
                        "input_items_sha256": payload.get("input_items"),
                        "tools_sha256": payload.get("tools"),
                        "request_payload_sha256": payload,
                    }
                    instructions = payload.get("instructions")
                    if (not isinstance(instructions, str)
                            or integrity.get("instructions_sha256")
                            != _sha256_text(instructions)):
                        errors.append(
                            f"turn {index} request_context hash mismatch: "
                            "instructions_sha256")
                    for hash_name, value in checks.items():
                        if integrity.get(hash_name) != _sha256_json(value):
                            errors.append(
                                f"turn {index} request_context hash mismatch: "
                                f"{hash_name}")
            model = turn.get("model")
            if isinstance(model, Mapping):
                for name in ("response_status", "incomplete_details",
                             "response_error"):
                    if name not in model:
                        errors.append(
                            f"turn {index} model missing response field: {name}")
                request_failed = turn.get("request_error") is not None
                if (not request_failed
                        and model.get("response_status") != "completed"):
                    errors.append(
                        f"turn {index} has non-completed provider response")
                if (not request_failed and model.get("incomplete_details")
                        not in (None, {}, [])):
                    errors.append(
                        f"turn {index} retains provider incomplete details")
                if (not request_failed and model.get("response_error")
                        not in (None, {}, [])):
                    errors.append(f"turn {index} retains provider response error")
    deliveries = result.get("protocol_deliveries")
    if not isinstance(deliveries, list):
        errors.append("protocol_deliveries must be a list")
    else:
        delivery_required = {
            "delivery_id", "sender", "recipient", "kind", "content",
            "content_sha256", "delivered_at_s", "read_at_turn", "read_at_s",
            "decision_delivery_status",
            "same_round_with_submission",
        }
        for index, delivery in enumerate(deliveries):
            if not isinstance(delivery, Mapping):
                errors.append(f"delivery {index} must be an object")
                continue
            errors.extend(
                f"delivery {index} missing field: {name}"
                for name in sorted(delivery_required - delivery.keys()))
            content = delivery.get("content")
            if (not isinstance(content, str)
                    or delivery.get("content_sha256") != _sha256_text(content)):
                errors.append(f"delivery {index} content hash mismatch")
            if delivery.get("decision_delivery_status") not in {
                    "delivered_before_decision", "delivered_after_decision",
                    "unread_channel_closed"}:
                errors.append(f"delivery {index} has invalid decision delivery status")
    calculator_calls = result.get("calculator_calls")
    if not isinstance(calculator_calls, list):
        errors.append("calculator_calls must be a list")
    else:
        calculator_required = {
            "calculator_call_id", "role", "model_turn_number", "input",
            "output", "expression_count", "started_at_s",
            "completed_at_s", "duration_s",
        }
        for index, call in enumerate(calculator_calls):
            if not isinstance(call, Mapping):
                errors.append(f"calculator call {index} must be an object")
                continue
            errors.extend(
                f"calculator call {index} missing field: {name}"
                for name in sorted(calculator_required - call.keys()))
            if call.get("calculator_call_id") != index + 1:
                errors.append(
                    f"calculator call {index} has nonsequential call id")
            call_input = call.get("input")
            expressions = (call_input.get("expressions")
                           if isinstance(call_input, Mapping) else None)
            if not isinstance(expressions, list):
                errors.append(
                    f"calculator call {index} input expressions must be a list")
            if not isinstance(call.get("output"), Mapping):
                errors.append(f"calculator call {index} output must be an object")
            for name in ("started_at_s", "completed_at_s", "duration_s"):
                value = call.get(name)
                if (not isinstance(value, (int, float))
                        or isinstance(value, bool) or value < 0):
                    errors.append(
                        f"calculator call {index} has invalid {name}")
            started = call.get("started_at_s")
            completed = call.get("completed_at_s")
            if (isinstance(started, (int, float))
                    and isinstance(completed, (int, float))
                    and completed < started):
                errors.append(
                    f"calculator call {index} completes before it starts")
        if isinstance(resources, Mapping):
            expected_expressions = sum(
                int(call.get("expression_count", 0))
                for call in calculator_calls if isinstance(call, Mapping))
            expected_time = sum(
                float(call.get("duration_s", 0.0))
                for call in calculator_calls if isinstance(call, Mapping)
                and isinstance(call.get("duration_s"), (int, float)))
            if resources.get("calculator_calls") != len(calculator_calls):
                errors.append("calculator call count does not match resources")
            if resources.get("calculator_expressions") != expected_expressions:
                errors.append(
                    "calculator expression count does not match resources")
            recorded_time = resources.get("calculator_time_s")
            if (not isinstance(recorded_time, (int, float))
                    or abs(float(recorded_time) - expected_time) > 1e-9):
                errors.append("calculator time does not match resources")
    prompt_integrity = result.get("prompt_integrity")
    if not isinstance(prompt_integrity, Mapping):
        errors.append("prompt_integrity must be an object")
    else:
        for role, integrity in prompt_integrity.items():
            if not isinstance(integrity, Mapping):
                errors.append(f"prompt_integrity for {role} must be an object")
                continue
            errors.extend(
                f"prompt_integrity for {role} missing field: {name}"
                for name in sorted(PROMPT_INTEGRITY_FIELDS - integrity.keys()))
            for name in PROMPT_INTEGRITY_FIELDS:
                if name in integrity and not _is_sha256(integrity[name]):
                    errors.append(
                        f"prompt_integrity for {role} is not SHA-256: {name}")

    accepted = result.get("accepted_branch_actions")
    if not isinstance(accepted, Mapping):
        errors.append("accepted_branch_actions must be an object")
    else:
        for branch, action in accepted.items():
            if branch not in {"1", "2"} or action not in {"A", "B"}:
                errors.append("accepted_branch_actions contains invalid entry")
    submission_audit = result.get("submission_audit")
    if not isinstance(submission_audit, Mapping):
        errors.append("submission_audit must be an object")
    else:
        for name in ("attempted", "accepted", "unapplied"):
            if not isinstance(submission_audit.get(name), list):
                errors.append(f"submission_audit {name} must be a list")
    process_summary = result.get("process_summary")
    if not isinstance(process_summary, Mapping):
        errors.append("process_summary must be an object")
    else:
        process_required = {
            "total_communication_rounds", "rounds_by_role",
            "messages_sent_by_role", "declines_by_role", "finishes_by_role",
            "automatic_protocol_closes_by_role", "wait_or_pass_turns_by_role",
            "final_decision_filed_round_by_role", "communication_close_reason",
            "submit_only_final_decision_phase_entered",
            "submit_only_phase_reason", "submit_only_phase_reason_code",
            "communication_continued_after_first_filing",
        }
        errors.extend(
            f"process_summary missing field: {name}"
            for name in sorted(process_required - process_summary.keys()))

    if status == "complete":
        if result.get("valid_submission") is not True:
            errors.append("complete result must be a valid submission")
        if result.get("organizational_failure") is not False:
            errors.append("complete result cannot be an organizational failure")
        if not isinstance(result.get("submitted"), str):
            errors.append("complete result must contain submitted plan")
        elif isinstance(accepted, Mapping):
            expected = {
                "1": result["submitted"][0],
                "2": result["submitted"][1],
            } if len(result["submitted"]) == 2 else {}
            if dict(accepted) != expected:
                errors.append(
                    "accepted_branch_actions do not match submitted plan")
    elif status == "organizational_terminal":
        if result.get("valid_submission") is not False:
            errors.append("organizational failure cannot be a valid submission")
        if result.get("organizational_failure") is not True:
            errors.append("organizational_terminal must mark organizational failure")
        if result.get("submitted") is not None:
            errors.append("organizational failure cannot contain a company plan")
        if result.get("decision_score") != 0.0:
            errors.append("organizational failure must receive score zero")
        if result.get("penalty_is_scoring_convention") is not True:
            errors.append("organizational failure must mark penalty convention")
    else:
        errors.append(f"unsupported analyzable status: {status}")
    if isinstance(economic_family, Mapping):
        try:
            rho = float(result.get("rho"))
            expected_score = (
                score_plan(dict(economic_family), rho, result.get("submitted"))
                if status == "complete"
                else score_organizational_failure(dict(economic_family), rho)
            )
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"cannot recompute outcome fields: {exc}")
        else:
            exact_checks = {
                "exact_optimum": expected_score["exact_optimum"],
                "valid_submission": expected_score["valid_submission"],
                "organizational_failure": expected_score["organizational_failure"],
                "failure_penalty": expected_score["failure_penalty"],
                "penalty_is_scoring_convention": expected_score[
                    "penalty_is_scoring_convention"],
            }
            for field, expected in exact_checks.items():
                if result.get(field) != expected:
                    errors.append(f"{field} does not match recomputed outcome")
            for field in ("raw_regret_m", "decision_score"):
                if not _same_number(result.get(field), expected_score[field]):
                    errors.append(f"{field} does not match recomputed outcome")
    return errors


def validate_result_record(result: Mapping[str, Any], status: str) -> None:
    errors = result_record_errors(result, status)
    if errors:
        raise DataRecordError("; ".join(errors))


def envelope_record_errors(envelope: Mapping[str, Any]) -> list[str]:
    status = envelope.get("status")
    if status == "confirmed_infrastructure_failure":
        from failure_policy import is_rerun_eligible
        errors = []
        resolution = envelope.get("inspection_resolution")
        if (not isinstance(resolution, Mapping)
                or resolution.get("decision") != "confirm_failure"
                or not isinstance(resolution.get("original_envelope"), str)
                or not _is_sha256(resolution.get(
                    "original_envelope_sha256"))):
            errors.append("confirmed infrastructure failure lacks valid resolution")
        if not is_rerun_eligible(str(envelope.get("failure_category"))):
            errors.append("confirmed failure has non-infrastructure cause")
        for field in VERSION_IDENTITY_FIELDS:
            if not isinstance(envelope.get(field), str) or not envelope[field]:
                errors.append(f"confirmed failure lacks {field}")
        if envelope.get("data_schema_version") != DATA_SCHEMA_VERSION:
            errors.append("confirmed failure has stale schema")
        return errors
    if status not in {"complete", "organizational_terminal"}:
        return []
    result = envelope.get("result")
    if not isinstance(result, Mapping):
        return ["terminal analyzable envelope lacks result object"]
    errors = result_record_errors(result, str(status))
    for field in ("design_version", "economic_generator_version",
                  "protocol_version", "data_schema_version"):
        if envelope.get(field) != result.get(field):
            errors.append(f"envelope {field} does not match result")
    return errors
