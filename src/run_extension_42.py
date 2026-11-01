"""Collect the 1,470 cells from the outcome-blind 42-family extension.

The original 2,100 archived cells remain untouched. New records are written
to a separate output folder and indexed with the original panel.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path

import yaml

from generator import RHO_GRID
from openrouter_client import OpenRouterResponsesClient, OpenRouterSettings
from organizations import ACTIVE_ORGANIZATIONS
from parallel_runner import ParallelPanelRunner, load_json, write_json_once_or_match
from schedule import build_schedule, validate_schedule
from seed_design import acceptance_reasons, build_frame, validate_frame


HERE = Path(__file__).resolve().parent
EXTENSION = HERE.parent / "data" / "extension_42"
COMBINED = EXTENSION / "combined_102_assigned_families.json"
AUDIT = EXTENSION / "combined_102_balance_audit.json"
BASE_INDEX = HERE.parent / "data" / "combined_exploratory_2100_with_recovery_index.json"
BASE_SUMMARY = HERE.parent / "data" / "combined_exploratory_2100_with_recovery_summary.json"
OUTPUT = HERE / "results_exploratory_extension_42_v18_gpt6_low"


def build_extension_schedule() -> tuple[dict, list[dict], list[dict], dict]:
    cfg = yaml.safe_load((HERE / "config.yaml").read_text())
    old, old_audit = build_frame(cfg)
    validate_frame(old, old_audit, cfg)
    payload = json.loads(COMBINED.read_text())
    frame = payload["families"]
    if len(frame) != 102 or frame[:60] != old:
        raise ValueError("extension would change the existing 60-family frame")
    if len({family["candidate_id"] for family in frame}) != 102:
        raise ValueError("duplicate economic candidate in combined frame")
    if [family["family_id"] for family in frame] != list(range(1, 103)):
        raise ValueError("extension family IDs must be 61 through 102")
    if any(acceptance_reasons(family, cfg) for family in frame[60:]):
        raise ValueError("extension economic family fails original acceptance rule")
    audit = json.loads(AUDIT.read_text())
    if (audit.get("combined_families") != 102
            or sorted(audit["economic_strata"].values()) != [17] * 6
            or audit.get("lead_branch_2_count") != 51):
        raise ValueError("extension balance audit is incomplete")
    base = json.loads(BASE_INDEX.read_text())
    summary = json.loads(BASE_SUMMARY.read_text())
    if (len(base.get("rows", [])) != 2100
            or summary.get("complete_cells") != 2100):
        raise ValueError("the original exploratory 2,100-cell panel is incomplete")

    schedule = build_schedule(frame, replicates=1, schedule_seed=20261013,
                              workers=64, replicate_waves=False)
    validate_schedule(schedule, families=102, replicates=1)
    selected = [cell for cell in schedule if cell["family_id"] >= 61]
    if len(selected) != 42 * len(RHO_GRID) * len(ACTIVE_ORGANIZATIONS):
        raise ValueError("extension schedule does not contain 1,470 cells")
    selected = [
        {**cell, "run_id": "extend3570__" + cell["run_id"],
         "scheduled_order": index + 1, "concurrency_lane": index % 64}
        for index, cell in enumerate(selected)
    ]
    if len({cell["run_id"] for cell in selected}) != 1470:
        raise ValueError("duplicate extension run ID")
    cells_per_family = Counter(cell["family_id"] for cell in selected)
    if set(cells_per_family.values()) != {35}:
        raise ValueError("each new family must run every organization and rho")

    metadata = {
        "purpose": "exploratory_extension_not_formal_collection",
        "source_design_version": cfg["design_version"],
        "combined_frame_sha256": hashlib.sha256(COMBINED.read_bytes()).hexdigest(),
        "balance_audit_sha256": hashlib.sha256(AUDIT.read_bytes()).hexdigest(),
        "original_2100_index_sha256": hashlib.sha256(BASE_INDEX.read_bytes()).hexdigest(),
        "original_2100_summary_sha256": hashlib.sha256(BASE_SUMMARY.read_bytes()).hexdigest(),
        "model": cfg["runtime"]["model"],
        "reasoning_effort": cfg["runtime"]["reasoning_effort"],
        "provider_order": cfg["runtime"]["openrouter_provider_order"],
        "workers": 64,
        "request_concurrency": 64,
        "cells": selected,
    }
    return cfg, frame, selected, metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true",
                        help="validate and save schedule without paid requests")
    parser.add_argument("--execute-live", action="store_true")
    args = parser.parse_args()
    if args.prepare == args.execute_live:
        parser.error("choose exactly one of --prepare or --execute-live")

    cfg, frame, selected, metadata = build_extension_schedule()
    runtime = cfg["runtime"]
    if (runtime["model"] != "openai/gpt-6-luna"
            or runtime["reasoning_effort"] != "low"
            or runtime["openrouter_provider_order"] != ["OpenAI"]):
        parser.error("extension must match the original GPT-6 Luna low / OpenAI setting")
    existing = load_json(OUTPUT / "execution_summary.json")
    if existing and existing.get("status") == "complete":
        parser.error("the 1,470-cell extension is already complete")
    write_json_once_or_match(OUTPUT / "extension_schedule.json", metadata)
    if args.prepare:
        print(json.dumps({"status": "prepared", "cells": len(selected),
                          "output_dir": str(OUTPUT)}))
        return 0

    settings = OpenRouterSettings.from_env(
        runtime["model"], reasoning_effort="low",
        temperature=runtime.get("temperature"),
        max_output_tokens=runtime["max_output_tokens_per_request"],
        timeout_s=runtime["api_timeout_s"],
        provider_order=("OpenAI",), allow_model_fallback=False)
    runner = ParallelPanelRunner(
        frame=frame, schedule=selected,
        client=OpenRouterResponsesClient(settings),
        output_dir=OUTPUT,
        dataset="exploratory_v18_low_extension_42",
        design_master_seed=cfg["economic_master_seed"],
        cell_workers=64, request_concurrency=64,
        transient_request_retries=runtime["transient_request_retries"],
        emergency_max_model_requests=runtime["emergency_max_model_requests"],
        emergency_max_messages=runtime["emergency_max_messages"],
        consecutive_empty_round_limit=runtime["consecutive_empty_round_limit"],
        expected_served_endpoint_model=runtime["observed_served_endpoint_model"],
        expected_provider="OpenAI",
        progress_filename="extension_progress.jsonl",
        summary_filename="execution_summary.json",
    )
    summary = asyncio.run(runner.run())
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "complete" else 3


if __name__ == "__main__":
    raise SystemExit(main())
