"""Collect the first 420 cells of the exploratory 3,570-cell panel."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import yaml

from openrouter_client import OpenRouterResponsesClient, OpenRouterSettings
from parallel_runner import ParallelPanelRunner, load_json, write_json_once_or_match
from seed_design import build_frame, validate_frame
from timing_design import FIRST_BLOCK_SEED, build_timing_schedule, validate_timing_schedule


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "results_parallel_stress_420_v18_gpt6_low"


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
        parser.error("this 420-cell batch is pinned to GPT-6 Luna low via OpenAI")
    frame, audit = build_frame(cfg)
    validate_frame(frame, audit, cfg)
    schedule = build_timing_schedule(frame, FIRST_BLOCK_SEED)
    validate_timing_schedule(schedule, frame)
    schedule = [
        {**cell, "run_id": "stress420__" + cell["run_id"],
         "concurrency_lane": index % 64}
        for index, cell in enumerate(schedule)
    ]
    existing = load_json(OUTPUT / "execution_summary.json")
    if existing and existing.get("status") == "complete":
        parser.error("the stress test is already complete")
    write_json_once_or_match(OUTPUT / "stress_schedule.json", {
        "purpose": "exploratory_parallel_stress_not_formal_timing",
        "source_design_version": cfg["design_version"],
        "workers": 64,
        "request_concurrency": 64,
        "cells": schedule,
    })
    settings = OpenRouterSettings.from_env(
        runtime["model"],
        reasoning_effort="low",
        temperature=runtime.get("temperature"),
        max_output_tokens=runtime["max_output_tokens_per_request"],
        timeout_s=runtime["api_timeout_s"],
        provider_order=("OpenAI",),
        allow_model_fallback=False,
    )
    runner = ParallelPanelRunner(
        frame=frame,
        schedule=schedule,
        client=OpenRouterResponsesClient(settings),
        output_dir=OUTPUT,
        dataset="exploratory_parallel_stress_420_v18_gpt6_low",
        design_master_seed=audit["master_seed"],
        cell_workers=64,
        request_concurrency=64,
        transient_request_retries=runtime["transient_request_retries"],
        emergency_max_model_requests=runtime["emergency_max_model_requests"],
        emergency_max_messages=runtime["emergency_max_messages"],
        consecutive_empty_round_limit=runtime["consecutive_empty_round_limit"],
        expected_served_endpoint_model=runtime["observed_served_endpoint_model"],
        expected_provider="OpenAI",
        progress_filename="stress_progress.jsonl",
        summary_filename="execution_summary.json",
    )
    summary = asyncio.run(runner.run())
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "complete" else 3


if __name__ == "__main__":
    raise SystemExit(main())
