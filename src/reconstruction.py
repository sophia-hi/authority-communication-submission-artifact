"""Populate the recorded reconstruction field for free-text communication.

The field belongs to the current result schema. Free-text messages and
action-only submissions do not provide a structured numerical score for it.
"""
from __future__ import annotations

from typing import Any


def score_reconstruction(family: dict, rho: float,
                         turn_log: list[dict]) -> dict[str, Any]:
    del family, rho, turn_log
    return {
        "applicable": False,
        "records": [],
        "local_within_1pct_fraction": None,
        "company_within_1pct_fraction": None,
        "scope": (
            "not applicable: all communication tools accept free text and "
            "final submission tools contain actions only"
        ),
    }
