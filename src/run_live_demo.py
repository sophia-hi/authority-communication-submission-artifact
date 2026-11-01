"""Run one archived task setting with autonomous agents in a separate demo dataset."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import yaml

from openrouter_client import OpenRouterResponsesClient, OpenRouterSettings
from organizations import ACTIVE_ORGANIZATIONS
from parallel_runner import ParallelPanelRunner, write_json_once_or_match
from schedule import replicate_id_hash
from seed_design import build_frame, validate_frame


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def demo_schedule(family: dict, rho: float, organizations: list[str]) -> list[dict]:
    """Use the actual task and role assignment with distinct demonstration run IDs."""
    return [dict(
        family_id=family["family_id"], candidate_id=family["candidate_id"],
        rho=rho, organization=organization, replicate=0,
        replicate_id_hash=replicate_id_hash(family["family_id"], rho, 0),
        lead_branch_index=family["lead_branch_index"],
        reporting_branch_index=family["reporting_branch_index"],
        scheduled_order=i, concurrency_lane=0, capture_request_text=True,
        run_id=f"demo__{organization}__f{family['family_id']:03d}__rho{round(rho * 100):03d}__r00",
    ) for i, organization in enumerate(organizations, 1)]


def check_output(path: Path) -> None:
    """Keep new demonstrations away from archived records and tracked code."""
    if path.is_relative_to(ROOT):
        relative = path.relative_to(ROOT)
        if len(relative.parts) < 2 or relative.parts[0] != "src" or not relative.parts[1].startswith("results_live_"):
            raise ValueError("within this repository, --out must be under src/results_live_*")
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError("--out must be a new or empty directory; existing runs are never overwritten")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", type=int, choices=range(1, 61), default=1, metavar="1..60",
                        help="family from the original 60-family frame (default: 1)")
    parser.add_argument("--rho", type=float, choices=[0, .25, .5, .75, 1], default=1)
    parser.add_argument("--organization", choices=[*ACTIVE_ORGANIZATIONS, "all"], default="mutual")
    parser.add_argument("--out", type=Path, default=HERE / "results_live_demo",
                        help="new/empty output directory (default: src/results_live_demo)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the plan without requests or files (default)")
    mode.add_argument("--execute-live", action="store_true", help="make paid provider requests")
    args = parser.parse_args(argv)

    cfg = yaml.safe_load((HERE / "config.yaml").read_text())
    runtime = cfg["runtime"]
    frame, audit = build_frame(cfg)
    validate_frame(frame, audit, cfg)
    family = next(f for f in frame if f["family_id"] == args.family)
    organizations = list(ACTIVE_ORGANIZATIONS) if args.organization == "all" else [args.organization]
    schedule = demo_schedule(family, args.rho, organizations)
    output = args.out.resolve()
    plan = dict(
        dataset="autonomous_reviewer_demo", cells=len(schedule), family_id=args.family,
        rho=args.rho, organizations=organizations, model=runtime["model"],
        expected_endpoint=runtime["observed_served_endpoint_model"],
        provider_order=runtime["openrouter_provider_order"],
        reasoning_effort=runtime["reasoning_effort"], temperature=runtime["temperature"],
        max_output_tokens=runtime["max_output_tokens_per_request"],
        capture_request_text=True, output=str(output), execute_live=args.execute_live,
    )
    print(json.dumps(plan, indent=2))
    if not args.execute_live:
        return 0
    try:
        check_output(output)
        settings = OpenRouterSettings.from_env(
            runtime["model"], reasoning_effort=runtime["reasoning_effort"],
            temperature=runtime["temperature"],
            max_output_tokens=runtime["max_output_tokens_per_request"],
            timeout_s=runtime["api_timeout_s"],
            provider_order=tuple(runtime["openrouter_provider_order"]),
        )
    except ValueError as error:
        parser.error(str(error))
    client = OpenRouterResponsesClient(settings)
    runner = ParallelPanelRunner(
        frame=[family], schedule=schedule, client=client, output_dir=output,
        dataset="autonomous_reviewer_demo", design_master_seed=audit["master_seed"],
        cell_workers=1, request_concurrency=2,
        transient_request_retries=runtime["transient_request_retries"],
        emergency_max_model_requests=runtime["emergency_max_model_requests"],
        emergency_max_messages=runtime["emergency_max_messages"],
        consecutive_empty_round_limit=runtime["consecutive_empty_round_limit"],
        expected_served_endpoint_model=runtime["observed_served_endpoint_model"],
        expected_provider="OpenAI",
    )
    write_json_once_or_match(output / "demo_schedule.json", dict(plan=plan, cells=schedule))
    summary = asyncio.run(runner.run())
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"] == "complete" else 3


if __name__ == "__main__":
    raise SystemExit(main())
