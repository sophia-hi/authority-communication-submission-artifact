"""Deterministic balanced selection for the first 420-cell collection block."""
from __future__ import annotations

import hashlib
import random
from collections import Counter

from generator import RHO_GRID
from organizations import ACTIVE_ORGANIZATIONS
from schedule import replicate_id_hash


FIRST_BLOCK_SEED = 2026101301


def _seed(master: int, label: str) -> int:
    raw = f"branch_pricing_v1|timing|{master}|{label}".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def timing_family_rhos(frame: list[dict], timing_seed: int) -> dict[int, float]:
    """Assign one rho per family with 3/3/3/3 labels and 6/6 Lead sides.

    The label quota uses the correct answer at the assigned rho. Seeded swaps
    preserve exactly 12 families per rho while satisfying both margins.
    """
    ordered = sorted(frame, key=lambda family: int(family["family_id"]))

    def imbalance(rho_indices: list[int]) -> int:
        penalty = 0
        for rho_index, rho in enumerate(RHO_GRID):
            members = [
                family for family, assigned in zip(ordered, rho_indices)
                if assigned == rho_index]
            labels = Counter(
                family["labeled_optima"][str(rho)] for family in members)
            leads = Counter(family["lead_branch_index"] for family in members)
            penalty += sum(abs(labels[label] - 3)
                           for label in ("AA", "AB", "BA", "BB"))
            penalty += sum(abs(leads[lead] - 6) for lead in (0, 1))
        return penalty

    for restart in range(32):
        rng = random.Random(_seed(
            timing_seed, f"balanced-allocation|{restart}"))
        rho_indices = [
            rho_index for rho_index in range(len(RHO_GRID)) for _ in range(12)]
        rng.shuffle(rho_indices)
        current = imbalance(rho_indices)
        for _ in range(100_000):
            left, right = rng.sample(range(len(ordered)), 2)
            if rho_indices[left] == rho_indices[right]:
                continue
            rho_indices[left], rho_indices[right] = (
                rho_indices[right], rho_indices[left])
            candidate = imbalance(rho_indices)
            if candidate <= current or rng.random() < 0.002:
                current = candidate
            else:
                rho_indices[left], rho_indices[right] = (
                    rho_indices[right], rho_indices[left])
            if current == 0:
                return {
                    int(family["family_id"]): float(RHO_GRID[rho_index])
                    for family, rho_index in zip(ordered, rho_indices)
                }
    raise ValueError("seeded timing allocation did not satisfy balance targets")


def build_timing_schedule(frame: list[dict], timing_seed: int) -> list[dict]:
    assignment = timing_family_rhos(frame, timing_seed)
    family_by_id = {int(f["family_id"]): f for f in frame}
    blocks = list(assignment.items())
    random.Random(_seed(timing_seed, "block-order")).shuffle(blocks)
    cells = []
    for block_order, (family_id, rho) in enumerate(blocks, 1):
        family = family_by_id[family_id]
        organizations = list(ACTIVE_ORGANIZATIONS)
        random.Random(_seed(
            timing_seed, f"organization-order|{family_id}|{rho:.2f}"),
        ).shuffle(organizations)
        for within_block_order, organization in enumerate(organizations, 1):
            cells.append({
                "family_id": family_id,
                "candidate_id": family["candidate_id"],
                "rho": rho,
                "organization": organization,
                "replicate": 0,
                "replicate_id_hash": replicate_id_hash(family_id, rho, 0),
                "lead_branch_index": family["lead_branch_index"],
                "reporting_branch_index": family["reporting_branch_index"],
                "timing_block_order": block_order,
                "timing_within_block_order": within_block_order,
                "scheduled_order": len(cells) + 1,
                "concurrency_lane": 0,
                "run_id": (
                    f"{organization}__f{family_id:03d}"
                    f"__rho{int(round(rho * 100)):03d}__r00"),
            })
    return cells


def validate_timing_schedule(schedule: list[dict], frame: list[dict]) -> None:
    if len(schedule) != len(frame) * len(ACTIVE_ORGANIZATIONS):
        raise ValueError("unexpected timing cell count")
    if len({cell["run_id"] for cell in schedule}) != len(schedule):
        raise ValueError("timing run IDs are not unique")
    family_rhos = {(c["family_id"], c["rho"]) for c in schedule}
    if len(family_rhos) != len(frame):
        raise ValueError("timing block must contain one rho per family")
    for family_id, rho in family_rhos:
        orgs = {c["organization"] for c in schedule
                if c["family_id"] == family_id and c["rho"] == rho}
        if orgs != set(ACTIVE_ORGANIZATIONS):
            raise ValueError("timing family-rho block is missing organizations")
    family_by_id = {int(f["family_id"]): f for f in frame}
    for rho in RHO_GRID:
        family_ids = {
            int(c["family_id"]) for c in schedule if c["rho"] == rho}
        if len(family_ids) != 12:
            raise ValueError("timing rho does not contain 12 families")
        labels = Counter(
            family_by_id[family_id]["labeled_optima"][str(rho)]
            for family_id in family_ids)
        if labels != Counter({"AA": 3, "AB": 3, "BA": 3, "BB": 3}):
            raise ValueError("timing rho answer labels are not 3/3/3/3")
        leads = Counter(
            family_by_id[family_id]["lead_branch_index"]
            for family_id in family_ids)
        if leads != Counter({0: 6, 1: 6}):
            raise ValueError("timing rho Lead sides are not 6/6")
