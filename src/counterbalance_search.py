"""Regenerate the seeded label-and-Lead counterbalance certificate.

Economic families are selected first. This search then changes only arbitrary
A/B mappings and Lead assignment. A zero penalty means every documented hard
balance constraint is satisfied. The selected certificate is stored separately
so ordinary frame reconstruction is fast and audits can verify it exactly.
"""
from __future__ import annotations

import argparse
from itertools import combinations
import json
from pathlib import Path
import random

import numpy as np
import yaml

from generator import RHO_GRID
from seed_design import (COUNTERBALANCE_FILE, HERE, LABEL_ASSIGNMENT_FILE,
                         minimum_give_way_imbalance, select_economic_families)


ALGORITHM_VERSION = "seeded_constrained_counterbalance_v2"
DIRECTION_TARGETS_LEAD = {
    0.25: {"premium": 6, "standard": 5},
    0.5: {"premium": 9, "standard": 11},
    0.75: {"premium": 15, "standard": 15},
    1.0: {"premium": 15, "standard": 15},
}
HARD_CONSTRAINTS = [
    "Lead is Branch 1 in 5 of 10 families within each economic stratum",
    "Each branch maps premium to A in 30 of 60 families",
    "At every rho, each role has correct label A in 29 to 31 families",
    "At rho 0 through .75, each answer label occurs 14 to 16 times",
    "At every rho, each answer label's counts across the two Lead sides differ by at most one",
    "Within every rho x economic stratum x Lead-side cell, each of AA, AB, BA, BB occurs 1 or 2 times",
    "At every rho, Lead and Reporting give-way counts attain the minimum feasible difference under five Lead sides per stratum",
    "At rho one, each answer label occurs 15 times and 7 or 8 times under each Lead side",
    "With economic families and label mappings fixed, give-way role by move direction attains the documented balanced feasible target at each nonzero rho",
]


def _inputs(frame: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    strata = sorted({
        (f["substantive_optima"]["1.0"], f["first_grid_switch_rho"])
        for f in frame})
    stratum_index = {value: index for index, value in enumerate(strata)}
    family_strata = np.array([
        stratum_index[(f["substantive_optima"]["1.0"],
                       f["first_grid_switch_rho"])]
        for f in frame], dtype=int)
    actions = np.array([[        
        [int(action == "premium")
         for action in f["substantive_optima"][str(rho)].split("|")]
        for rho in RHO_GRID]
        for f in frame], dtype=int)
    local = np.array([
        [int(action == "premium") for action in f["local_plan"].split("|")]
        for f in frame], dtype=int)
    return family_strata, actions, local


def _penalty(state: np.ndarray, family_strata: np.ndarray,
             actions: np.ndarray, local: np.ndarray,
             minimum_give_way_differences: list[int]) -> int:
    """Return zero exactly when all frozen balance constraints hold."""
    family_count = len(state)
    lead = state[:, 0]
    maps = state[:, 1:]
    penalty = 50 * (
        abs(int(maps[:, 0].sum()) - 30)
        + abs(int(maps[:, 1].sum()) - 30))
    for stratum in range(6):
        penalty += 50 * abs(int(lead[family_strata == stratum].sum()) - 5)

    for rho_index in range(len(RHO_GRID)):
        # A is encoded as equality between the substantive premium indicator
        # and the premium-to-A mapping indicator.
        answer_a = actions[:, rho_index, :] == maps
        lead_a = np.array([
            answer_a[index, lead[index]] for index in range(family_count)])
        reporting_a = np.array([
            answer_a[index, 1 - lead[index]] for index in range(family_count)])
        for count in (int(lead_a.sum()), int(reporting_a.sum())):
            penalty += 30 * max(0, 29 - count, count - 31)

        changed_at_rho = local != actions[:, rho_index, :]
        both_at_rho = changed_at_rho.all(axis=1)
        lead_gives_at_rho = np.array([
            changed_at_rho[index, lead[index]]
            for index in range(family_count)]) & ~both_at_rho
        reporting_gives_at_rho = np.array([
            changed_at_rho[index, 1 - lead[index]]
            for index in range(family_count)]) & ~both_at_rho
        lead_give_count = int(lead_gives_at_rho.sum())
        reporting_give_count = int(reporting_gives_at_rho.sum())
        penalty += 30 * max(
            0, abs(lead_give_count - reporting_give_count)
            - minimum_give_way_differences[rho_index])

        # Branch 1 is the high bit and Branch 2 the low bit:
        # BB=0, BA=1, AB=2, AA=3.
        answer = answer_a[:, 0].astype(int) * 2 + answer_a[:, 1].astype(int)
        counts = np.bincount(answer, minlength=4)
        if rho_index == len(RHO_GRID) - 1:
            penalty += 30 * int(np.abs(counts - 15).sum())
        else:
            penalty += 8 * int(np.maximum(
                np.maximum(14 - counts, counts - 16), 0).sum())
        for label in range(4):
            side_0 = int(((answer == label) & (lead == 0)).sum())
            side_1 = int(((answer == label) & (lead == 1)).sum())
            penalty += 12 * max(0, abs(side_0 - side_1) - 1)
        for stratum in range(6):
            for lead_side in (0, 1):
                cell = answer[(family_strata == stratum) & (lead == lead_side)]
                cell_counts = np.bincount(cell, minlength=4)
                penalty += 8 * int(np.maximum(
                    np.maximum(1 - cell_counts, cell_counts - 2), 0).sum())
    return int(penalty)


def _fixed_label_maps(frame: list[dict], certificate_path: Path) -> np.ndarray:
    """Read the immutable label artifact; Lead searches cannot change it."""
    certificate = json.loads(certificate_path.read_text())
    by_candidate = {
        int(row["candidate_id"]): row for row in certificate["assignments"]}
    return np.array([[
        int(by_candidate[int(family["candidate_id"])][
            f"branch{branch}_premium_label"] == "A")
        for branch in (1, 2)
    ] for family in frame], dtype=int)


def search_lead_assignment(
        frame: list[dict], seed: int, fixed_maps: np.ndarray) -> np.ndarray:
    """Exact seeded search over Lead sides while label maps stay unchanged."""
    family_strata, actions, local = _inputs(frame)
    minimum_give_way_differences = [
        minimum_give_way_imbalance(frame, rho) for rho in RHO_GRID]
    family_count = len(frame)
    answer_a = actions == fixed_maps[:, None, :]
    answer_code = (
        answer_a[:, :, 0].astype(int) * 2
        + answer_a[:, :, 1].astype(int))
    changed = local[:, None, :] != actions
    single_change = changed.sum(axis=2) == 1
    changed_branch = np.argmax(changed, axis=2)
    changed_action = np.take_along_axis(
        actions, changed_branch[:, :, None], axis=2)[:, :, 0]

    rng = random.Random(seed)
    options_by_stratum: list[list[tuple]] = []
    for stratum in range(6):
        indices = np.where(family_strata == stratum)[0].tolist()
        combinations_in_seeded_order = list(combinations(indices, 5))
        rng.shuffle(combinations_in_seeded_order)
        options = []
        for chosen in combinations_in_seeded_order:
            lead = np.zeros(family_count, dtype=int)
            lead[list(chosen)] = 1
            if any(
                    any(value not in (1, 2) for value in np.bincount(
                        answer_code[(family_strata == stratum) & (lead == side),
                                    rho_index], minlength=4))
                    for rho_index in range(len(RHO_GRID)) for side in (0, 1)):
                continue
            lead_a = tuple(int(answer_a[
                np.arange(family_count), rho_index, lead][
                    family_strata == stratum].sum())
                for rho_index in range(len(RHO_GRID)))
            side_one = tuple(
                int(((answer_code[:, rho_index] == label)
                     & (lead == 1) & (family_strata == stratum)).sum())
                for rho_index in range(len(RHO_GRID)) for label in range(4))
            lead_direction = tuple(
                int((single_change[:, rho_index]
                     & (changed_branch[:, rho_index] == lead)
                     & (changed_action[:, rho_index] == direction)
                     & (family_strata == stratum)).sum())
                for rho_index in range(len(RHO_GRID)) for direction in (1, 0))
            options.append((chosen, lead_a, side_one, lead_direction))
        options_by_stratum.append(options)

    side_targets = []
    for rho_index in range(len(RHO_GRID)):
        for label in range(4):
            total = int((answer_code[:, rho_index] == label).sum())
            side_targets.append({total // 2, (total + 1) // 2})
    direction_targets = []
    for rho in RHO_GRID:
        target = DIRECTION_TARGETS_LEAD.get(float(rho), {})
        direction_targets.extend((
            int(target.get("premium", 0)), int(target.get("standard", 0))))

    solution: list[tuple] | None = None

    def feasible(values: tuple[int, ...], remaining: int,
                 targets: list[set[int]]) -> bool:
        return all(
            value <= max(targets[index])
            and value + 5 * remaining >= min(targets[index])
            for index, value in enumerate(values))

    def visit(stratum: int, lead_a: tuple[int, ...],
              side_one: tuple[int, ...], direction: tuple[int, ...],
              selected: list[tuple]) -> bool:
        nonlocal solution
        if stratum == 6:
            if (all(29 <= value <= 31 for value in lead_a)
                    and all(side_one[index] in side_targets[index]
                            for index in range(len(side_one)))
                    and direction == tuple(direction_targets)):
                solution = list(selected)
                return True
            return False
        remaining = 5 - stratum
        for option in options_by_stratum[stratum]:
            next_lead_a = tuple(a + b for a, b in zip(lead_a, option[1]))
            next_side = tuple(a + b for a, b in zip(side_one, option[2]))
            next_direction = tuple(a + b for a, b in zip(direction, option[3]))
            if not feasible(next_lead_a, remaining, [{29, 30, 31}] * 5):
                continue
            if not feasible(next_side, remaining, side_targets):
                continue
            if any(
                    value > direction_targets[index]
                    or value + 5 * remaining < direction_targets[index]
                    for index, value in enumerate(next_direction)):
                continue
            if visit(stratum + 1, next_lead_a, next_side, next_direction,
                     selected + [option]):
                return True
        return False

    zeros5, zeros20, zeros10 = (0,) * 5, (0,) * 20, (0,) * 10
    if not visit(0, zeros5, zeros20, zeros10, []):
        raise RuntimeError("counterbalance search found no feasible Lead assignment")
    state = np.column_stack((
        np.zeros(family_count, dtype=int), fixed_maps))
    assert solution is not None
    for option in solution:
        state[list(option[0]), 0] = 1
    if _penalty(
            state, family_strata, actions, local,
            minimum_give_way_differences) != 0:
        raise RuntimeError("direction-balanced assignment violates prior constraints")
    return state


def certificate(frame: list[dict], state: np.ndarray, seed: int) -> dict:
    assignments = []
    for family_id, (family, values) in enumerate(zip(frame, state), 1):
        lead, branch1, branch2 = (int(value) for value in values)
        assignments.append({
            "family_id": family_id,
            "candidate_id": int(family["candidate_id"]),
            "economic_stratum": {
                "substantive_rho1_optimum": family["substantive_optima"]["1.0"],
                "first_switch_rho": family["first_grid_switch_rho"],
            },
            "lead_branch_index": lead,
            "branch1_premium_label": "A" if branch1 else "B",
            "branch2_premium_label": "A" if branch2 else "B",
        })
    return {
        "algorithm_version": ALGORITHM_VERSION,
        "counterbalance_seed": seed,
        "selection_rule": (
            "first exact feasible Lead assignment found in seeded option order, "
            "with the v1 label maps and all 60 economic families held fixed; "
            "certificate is keyed by candidate_id and revalidated on every frame build"),
        "hard_constraints": HARD_CONSTRAINTS,
        "assignments": assignments,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path,
                        help="write a regenerated certificate to a separate file")
    args = parser.parse_args()
    cfg = yaml.safe_load((HERE / "config.yaml").read_text())
    frame, _, _ = select_economic_families(cfg)
    seed = int(cfg["counterbalance_seed"])
    fixed_maps = _fixed_label_maps(frame, LABEL_ASSIGNMENT_FILE)
    state = search_lead_assignment(frame, seed, fixed_maps)
    output = certificate(frame, state, seed)
    if args.out:
        args.out.write_text(json.dumps(output, indent=2) + "\n")
        print(json.dumps({"output": str(args.out), "families": len(frame)}, indent=2))
    else:
        if json.loads(COUNTERBALANCE_FILE.read_text()) != output:
            raise ValueError("regenerated counterbalance differs from archived certificate")
        print("Verified archived 60-family counterbalance certificate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
