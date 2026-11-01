"""Collect the remaining 1,680 cells in the 60-family exploratory panel."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import yaml

from openrouter_client import OpenRouterResponsesClient, OpenRouterSettings
from parallel_runner import ParallelPanelRunner, load_json, write_json_once_or_match
from schedule import build_schedule, validate_schedule
from seed_design import build_frame, validate_frame
from timing_design import FIRST_BLOCK_SEED, build_timing_schedule, validate_timing_schedule


HERE = Path(__file__).resolve().parent
FIRST = HERE / "results_parallel_stress_420_v18_gpt6_low"
OUTPUT = HERE / "results_exploratory_remaining_1680_v18_gpt6_low"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-live", action="store_true")
    args = parser.parse_args()
    if not args.execute_live:
        parser.error("refusing paid requests without --execute-live")

    cfg = yaml.safe_load((HERE / "config.yaml").read_text())
    runtime = cfg["runtime"]
    if (runtime["model"] != "openai/gpt-6-luna"
            or runtime["reasoning_effort"] != "low"
            or runtime["openrouter_provider_order"] != ["OpenAI"]):
        parser.error("this exploratory panel is pinned to GPT-6 Luna low via OpenAI")

    frame, audit = build_frame(cfg)
    validate_frame(frame, audit, cfg)
    first_schedule = build_timing_schedule(frame, FIRST_BLOCK_SEED)
    validate_timing_schedule(first_schedule, frame)
    first_summary = load_json(FIRST / "execution_summary.json")
    if not first_summary or first_summary.get("status") != "complete" \
            or first_summary.get("terminal_validation", {}).get("valid") is not True:
        parser.error("the isolated first 420 cells are not complete and valid")
    first_ids = {cell["run_id"] for cell in first_schedule}
    for cell in first_schedule:
        record = load_json(FIRST / ("stress420__" + cell["run_id"] + ".json"))
        if (not record or record.get("status") != "complete"
                or record.get("schedule", {}).get("run_id")
                != "stress420__" + cell["run_id"]):
            parser.error("the first 420 result records are incomplete or changed")

    full = build_schedule(frame, replicates=1, schedule_seed=20261013,
                          workers=4, replicate_waves=True)
    validate_schedule(full, families=60, replicates=1)
    remaining = [cell for cell in full
                 if cell["run_id"] not in first_ids]
    if len(remaining) != 1680:
        parser.error("remaining exploratory schedule is not 1,680 cells")
    schedule = [
        {**cell, "run_id": "explore2100__" + cell["run_id"],
         "scheduled_order": index + 1, "concurrency_lane": index % 64}
        for index, cell in enumerate(remaining)
    ]
    existing = load_json(OUTPUT / "execution_summary.json")
    if existing and existing.get("status") == "complete":
        parser.error("the remaining 1,680 cells are already complete")
    write_json_once_or_match(OUTPUT / "remaining_schedule.json", {
        "purpose": "exploratory_completion_not_formal_collection",
        "source_design_version": cfg["design_version"],
        "first_420_schedule_sha256": hashlib.sha256(
            (FIRST / "stress_schedule.json").read_bytes()).hexdigest(),
        "first_420_summary_sha256": hashlib.sha256(
            (FIRST / "execution_summary.json").read_bytes()).hexdigest(),
        "workers": 64,
        "request_concurrency": 64,
        "cells": schedule,
    })
    settings = OpenRouterSettings.from_env(
        runtime["model"], reasoning_effort="low",
        temperature=runtime.get("temperature"),
        max_output_tokens=runtime["max_output_tokens_per_request"],
        timeout_s=runtime["api_timeout_s"],
        provider_order=("OpenAI",), allow_model_fallback=False)
    runner = ParallelPanelRunner(
        frame=frame, schedule=schedule,
        client=OpenRouterResponsesClient(settings),
        output_dir=OUTPUT,
        dataset="exploratory_v18_low_completion_1680",
        design_master_seed=audit["master_seed"],
        cell_workers=64, request_concurrency=64,
        transient_request_retries=runtime["transient_request_retries"],
        emergency_max_model_requests=runtime["emergency_max_model_requests"],
        emergency_max_messages=runtime["emergency_max_messages"],
        consecutive_empty_round_limit=runtime["consecutive_empty_round_limit"],
        expected_served_endpoint_model=runtime["observed_served_endpoint_model"],
        expected_provider="OpenAI",
        progress_filename="remaining_progress.jsonl",
        summary_filename="execution_summary.json",
    )
    summary = asyncio.run(runner.run())
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "complete" else 3


if __name__ == "__main__":
    raise SystemExit(main())
