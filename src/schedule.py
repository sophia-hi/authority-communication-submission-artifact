"""Reproducible treatment schedule with explicit concurrency lanes."""
from __future__ import annotations

import hashlib
import random

from generator import RHO_GRID
from organizations import ACTIVE_ORGANIZATIONS


def replicate_id_hash(family_id: int, rho: float, replicate: int) -> int:
    """Deterministic audit identifier; it is not sent to the model API."""
    payload = f"branch_pricing_v1|{family_id}|{rho:.2f}|{replicate}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def replicate_wave_seed(schedule_seed: int, replicate: int) -> int:
    payload = f"branch_pricing_v1|schedule|{schedule_seed}|{replicate}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def build_schedule(frame: list[dict], replicates: int, schedule_seed: int,
                   workers: int = 1,
                   replicate_waves: bool = False) -> list[dict]:
    if replicates < 1:
        raise ValueError("replicates must be positive")
    if workers < 1:
        raise ValueError("workers must be positive")
    cells = []
    for family in frame:
        for rho in RHO_GRID:
            for organization in ACTIVE_ORGANIZATIONS:
                for rep in range(replicates):
                    cells.append({
                        "family_id": family["family_id"],
                        "candidate_id": family["candidate_id"],
                        "rho": rho,
                        "organization": organization,
                        "replicate": rep,
                        "replicate_id_hash": replicate_id_hash(
                            family["family_id"], rho, rep),
                        "lead_branch_index": family["lead_branch_index"],
                        "reporting_branch_index": family["reporting_branch_index"],
                    })
    if replicate_waves:
        waves = []
        for replicate in range(replicates):
            wave = [cell for cell in cells
                    if cell["replicate"] == replicate]
            random.Random(replicate_wave_seed(
                int(schedule_seed), replicate)).shuffle(wave)
            for wave_order, cell in enumerate(wave, 1):
                cell["replicate_wave"] = replicate
                cell["wave_order"] = wave_order
            waves.extend(wave)
        cells = waves
    else:
        random.Random(int(schedule_seed)).shuffle(cells)
    for index, cell in enumerate(cells, 1):
        cell["scheduled_order"] = index
        cell["concurrency_lane"] = (index - 1) % workers
        cell["run_id"] = (
            f"{cell['organization']}__f{cell['family_id']:03d}"
            f"__rho{int(round(cell['rho'] * 100)):03d}"
            f"__r{cell['replicate']:02d}"
        )
    return cells


def validate_schedule(schedule: list[dict], families: int,
                      replicates: int) -> None:
    expected = families * len(RHO_GRID) * len(ACTIVE_ORGANIZATIONS) * replicates
    assert len(schedule) == expected
    assert len({x["run_id"] for x in schedule}) == expected
    keys = {(x["family_id"], x["rho"], x["organization"], x["replicate"])
            for x in schedule}
    assert len(keys) == expected
