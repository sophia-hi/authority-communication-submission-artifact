"""Deterministic protocol-and-scoring mock over the experimental grid.

The mock supplies scripted actions and known optimal answers. It does not
invoke agent prompts, autonomous model behaviour, the live cell executor, or a
provider API.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from organizations import ACTIVE_ORGANIZATIONS
from protocol import ProtocolState
from scoring import score_plan
from seed_design import build_frame, validate_frame


HERE = Path(__file__).resolve().parent


def _component(plan: str, branch_index: int) -> str:
    return plan[branch_index]


def run_mock_cell(family: dict, rho: float, organization: str) -> dict:
    plan = family["labeled_optima"][str(rho)]
    lead = family["lead_branch_index"]
    reporting = family["reporting_branch_index"]
    state = ProtocolState(organization, lead)

    if organization == "single":
        state.submit_company("Owner", plan[0], plan[1])
    elif organization == "independent":
        state.submit_branch("Branch 1 Specialist", _component(plan, 0))
        state.submit_branch("Branch 2 Specialist", _component(plan, 1))
    elif organization == "committed_handoff":
        state.commit_and_handoff(
            "Reporting", _component(plan, reporting),
            "mock sufficient statistics and committed local action")
        state.submit_branch("Lead", _component(plan, lead))
    elif organization == "informational_handoff":
        state.send_report("Reporting", "mock sufficient statistics without action")
        state.submit_branch("Reporting", _component(plan, reporting))
        state.submit_branch("Lead", _component(plan, lead))
    elif organization == "mutual":
        state.send_message(
            "Branch 2 Specialist", "mock local sufficient statistics")
        state.send_message(
            "Branch 1 Specialist", "mock interaction interpretation")
        state.submit_branch("Branch 2 Specialist", _component(plan, 1))
        state.submit_branch("Branch 1 Specialist", _component(plan, 0))
    elif organization == "specialist_proactive":
        state.send_report("Reporting", "mock proactive sufficient statistics")
        state.submit_company("Lead", plan[0], plan[1])
    elif organization == "centralized_two_way":
        state.send_message("Reporting", "mock initial sufficient statistics")
        state.send_message("Lead", "mock clarification request")
        state.send_message("Reporting", "mock clarification response")
        state.submit_company("Lead", plan[0], plan[1])
    else:
        raise AssertionError(organization)

    assembled = state.assembled_actions()
    if assembled is None:
        raise AssertionError(f"mock did not finish {organization}")
    compact = "".join(assembled)
    scored = score_plan(family, rho, compact)
    return {
        "family_id": family["family_id"],
        "candidate_id": family["candidate_id"],
        "rho": rho,
        "organization": organization,
        "lead_branch_index": lead,
        "reporting_branch_index": reporting,
        "submitted": compact,
        **scored,
        "events": [event.__dict__ for event in state.events],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--families", type=int, default=2)
    p.add_argument("--rhos", default="0,0.5,1")
    p.add_argument("--out", default="results_mock_acceptance")
    args = p.parse_args()
    cfg = yaml.safe_load((HERE / "config.yaml").read_text())
    frame, audit = build_frame(cfg)
    validate_frame(frame, audit, cfg)
    rhos = [float(x.strip()) for x in args.rhos.split(",") if x.strip()]
    rows = [
        run_mock_cell(family, rho, organization)
        for family in frame[:args.families]
        for rho in rhos
        for organization in ACTIVE_ORGANIZATIONS
    ]
    out = HERE / args.out
    out.mkdir(parents=True, exist_ok=True)
    temp = out / "runs.jsonl.tmp"
    temp.write_text("".join(json.dumps(row) + "\n" for row in rows))
    temp.replace(out / "runs.jsonl")
    summary = {
        "cells": len(rows),
        "families": args.families,
        "rhos": rhos,
        "organizations": list(ACTIVE_ORGANIZATIONS),
        "all_terminal": all(row["submitted"] for row in rows),
        "all_exact": all(row["exact_optimum"] for row in rows),
        "unique_keys": len({
            (r["family_id"], r["rho"], r["organization"]) for r in rows}),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
