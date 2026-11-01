"""Outcome and resource summaries for the recorded experimental cells."""
from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any, Iterable, Mapping

from data_schema import validate_result_record


PERFORMANCE_FIELDS = ("raw_regret_m", "decision_score", "exact_optimum")
RESOURCE_FIELDS = (
    "model_requests", "input_tokens", "output_tokens", "reasoning_tokens",
    "total_tokens", "known_input_tokens", "known_output_tokens",
    "known_reasoning_tokens", "known_total_tokens",
    "communication_actions", "provider_latency_s",
    "queue_delay_s", "wall_time_s", "parallel_overlap_s", "cost_usd",
    "known_cost_usd", "requests_with_unknown_cost",
    "request_retries", "requests_with_unknown_usage",
    "failed_request_time_s", "retry_wait_s",
    "calculator_calls", "calculator_expressions", "calculator_time_s",
)
PROCESS_SCALAR_FIELDS = (
    "total_communication_rounds",
    "submit_only_final_decision_phase_entered",
    "communication_continued_after_first_filing",
)


def _means(rows: list[Mapping[str, Any]], fields: tuple[str, ...]) -> dict[str, float | None]:
    output: dict[str, float | None] = {}
    for field in fields:
        values = [row[field] for row in rows
                  if isinstance(row.get(field), (int, float))
                  and not isinstance(row.get(field), bool)]
        if field == "exact_optimum" or any(
                isinstance(row.get(field), bool) for row in rows):
            values = [float(bool(row[field])) for row in rows
                      if isinstance(row.get(field), bool)]
        output[field] = mean(values) if values else None
    return output


def _cost_reporting(rows: list[Mapping[str, Any]],
                    unknown_attempts: int = 0) -> dict[str, Any]:
    """Keep known cost separate from an unavailable complete total."""
    model_requests = sum(int(row.get("model_requests", 0)) for row in rows)
    unknown_requests = sum(
        int(row.get("requests_with_unknown_cost", 0)) for row in rows)
    known_subtotal = sum(float(row.get("known_cost_usd", 0.0)) for row in rows)
    complete = unknown_requests == 0 and unknown_attempts == 0
    incomplete_cells = (sum(row.get("cost_complete") is not True for row in rows)
                        + unknown_attempts)
    return {
        "known_cost_subtotal_usd": known_subtotal,
        "total_cost_usd": known_subtotal if complete else None,
        "cost_complete": complete,
        "cells_with_incomplete_cost": incomplete_cells,
        "cell_cost_missing_rate": (
            incomplete_cells / (len(rows) + unknown_attempts)
            if rows or unknown_attempts else None),
        "attempts_with_unknown_resources": unknown_attempts,
        "requests_with_unknown_cost": unknown_requests,
        "request_cost_missing_rate": (
            unknown_requests / model_requests if model_requests else None),
    }


def _usage_reporting(rows: list[Mapping[str, Any]],
                     unknown_attempts: int = 0) -> dict[str, Any]:
    unknown_requests = sum(
        int(row.get("requests_with_unknown_usage", 0)) for row in rows)
    incomplete_cells = (sum(row.get("usage_complete") is not True for row in rows)
                        + unknown_attempts)
    return {
        "known_input_token_subtotal": sum(
            float(row.get("known_input_tokens", 0)) for row in rows),
        "known_output_token_subtotal": sum(
            float(row.get("known_output_tokens", 0)) for row in rows),
        "known_total_token_subtotal": sum(
            float(row.get("known_total_tokens", 0)) for row in rows),
        "usage_complete": unknown_requests == 0 and unknown_attempts == 0,
        "attempts_with_unknown_resources": unknown_attempts,
        "cells_with_incomplete_usage": incomplete_cells,
        "cell_usage_missing_rate": (
            incomplete_cells / (len(rows) + unknown_attempts)
            if rows or unknown_attempts else None),
        "requests_with_unknown_usage": unknown_requests,
    }


def _group_summary(envelopes: list[Mapping[str, Any]]) -> dict[str, Any]:
    analyzable = [x for x in envelopes if x.get("status") in {
        "complete", "organizational_terminal"}]
    results = [x.get("result") for x in analyzable
               if isinstance(x.get("result"), Mapping)]
    for envelope in analyzable:
        result = envelope.get("result")
        if isinstance(result, Mapping):
            validate_result_record(result, str(envelope["status"]))
    valid = [x for x in results if x.get("valid_submission") is True]
    failed = [x for x in results if x.get("organizational_failure") is True]
    resource_rows = [x["resources"] for x in results
                     if isinstance(x.get("resources"), Mapping)]
    process_rows = [x["process_summary"] for x in results
                    if isinstance(x.get("process_summary"), Mapping)]
    all_attempt_resource_rows = [
        attempt["resources"]
        for envelope in envelopes
        for attempt in envelope.get("attempts", [])
        if isinstance(attempt, Mapping)
        and isinstance(attempt.get("resources"), Mapping)
    ]
    if not all_attempt_resource_rows:
        all_attempt_resource_rows = resource_rows
    unknown_attempts = sum(
        not isinstance(attempt.get("resources"), Mapping)
        or attempt.get("resources_complete") is False
        for envelope in envelopes
        for attempt in envelope.get("attempts", [])
        if isinstance(attempt, Mapping))
    failed_resources = [x["resources"] for x in failed
                        if isinstance(x.get("resources"), Mapping)]
    categories = Counter(str(x.get("failure_category", "unspecified"))
                         for x in failed)
    confirmed_missing_categories = Counter(
        str(envelope.get("failure_category", "unspecified"))
        for envelope in envelopes
        if envelope.get("status") == "confirmed_infrastructure_failure")
    rerun_categories = Counter(
        str(attempt.get("failure_category", "unspecified"))
        for envelope in envelopes
        if len(envelope.get("attempts", [])) > 1
        for attempt in envelope.get("attempts", [])[:-1]
        if isinstance(attempt, Mapping))
    denominator = len(valid) + len(failed)
    return {
        "scheduled_envelopes": len(envelopes),
        "analyzable_cells": denominator,
        "valid_submissions": len(valid),
        "organizational_failures": len(failed),
        "unresolved_infrastructure_failures": sum(
            x.get("status") in {"infrastructure_failure",
                                "inspection_required", "running"}
            for x in envelopes),
        "confirmed_infrastructure_failures": sum(
            x.get("status") == "confirmed_infrastructure_failure"
            for x in envelopes),
        "organizational_failure_rate": (
            len(failed) / denominator if denominator else None),
        "failure_categories": dict(sorted(categories.items())),
        "confirmed_missing_failure_categories": dict(
            sorted(confirmed_missing_categories.items())),
        "documented_rerun_causes": dict(sorted(rerun_categories.items())),
        "unconditional_performance": _means(results, PERFORMANCE_FIELDS),
        "conditional_decision_quality": _means(valid, PERFORMANCE_FIELDS),
        "resources_per_analyzable_cell": _means(
            resource_rows, RESOURCE_FIELDS),
        "resources_across_all_attempts": _means(
            all_attempt_resource_rows, RESOURCE_FIELDS),
        "resources_for_organizational_failures": _means(
            failed_resources, RESOURCE_FIELDS),
        "process_measures": {
            "means": _means(process_rows, PROCESS_SCALAR_FIELDS),
            "communication_close_reasons": dict(sorted(Counter(
                str(row.get("communication_close_reason", "unspecified"))
                for row in process_rows).items())),
            "submit_only_phase_reasons": dict(sorted(Counter(
                str(row.get("submit_only_phase_reason_code", "none"))
                for row in process_rows).items())),
            "declines_by_role": dict(sorted(Counter({
                role: sum(int(count) for row in process_rows
                          for role2, count in row.get(
                              "declines_by_role", {}).items() if role2 == role)
                for role in {role for row in process_rows
                             for role in row.get("declines_by_role", {})}
            }).items())),
            "finishes_by_role": dict(sorted(Counter({
                role: sum(int(count) for row in process_rows
                          for role2, count in row.get(
                              "finishes_by_role", {}).items() if role2 == role)
                for role in {role for row in process_rows
                             for role in row.get("finishes_by_role", {})}
            }).items())),
        },
        "cost_reporting": _cost_reporting(
            all_attempt_resource_rows, unknown_attempts),
        "usage_reporting": _usage_reporting(
            all_attempt_resource_rows, unknown_attempts),
        "documented_rerun_cells": sum(
            len(envelope.get("attempts", [])) > 1 for envelope in envelopes),
    }


def summarize_outcome_envelopes(
        envelopes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Report unconditional, conditional, and failure outcomes by treatment.

    Infrastructure failures are counted but excluded from the organizational
    failure denominator because they remain resumable missingness.
    """
    materialized = list(envelopes)
    by_organization: dict[str, list[Mapping[str, Any]]] = {}
    by_organization_rho: dict[tuple[str, float], list[Mapping[str, Any]]] = {}
    for envelope in materialized:
        schedule = envelope.get("schedule")
        result = envelope.get("result")
        source = schedule if isinstance(schedule, Mapping) else result
        if not isinstance(source, Mapping):
            continue
        organization = source.get("organization")
        rho = source.get("rho")
        if not isinstance(organization, str) or not isinstance(rho, (int, float)):
            continue
        by_organization.setdefault(organization, []).append(envelope)
        by_organization_rho.setdefault((organization, float(rho)), []).append(
            envelope)
    return {
        "organization": {
            organization: _group_summary(rows)
            for organization, rows in sorted(by_organization.items())
        },
        "organization_by_rho": {
            f"{organization}|rho={rho:g}": _group_summary(rows)
            for (organization, rho), rows in sorted(by_organization_rho.items())
        },
    }
