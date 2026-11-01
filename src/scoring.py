"""Hidden scoring for labeled A/B company actions."""
from __future__ import annotations

from generator import decision_score


def labeled_to_substantive(plan: str, label_maps: list[dict[str, str]]) -> str:
    if len(plan) != 2 or any(x not in "AB" for x in plan):
        raise ValueError(f"invalid labeled plan {plan!r}")
    inverse = [{label: action for action, label in mapping.items()}
               for mapping in label_maps]
    return inverse[0][plan[0]] + "|" + inverse[1][plan[1]]


def score_plan(
        family: dict, rho: float, plan: str
) -> dict[str, float | str | bool | None]:
    key = str(float(rho))
    substantive = labeled_to_substantive(plan, family["label_maps"])
    values = family["utilities"][key]
    optimum = family["labeled_optima"][key]
    raw = values[substantive]
    best = max(values.values())
    return {
        "submitted_plan": plan,
        "substantive_plan": substantive,
        "optimal_plan": optimum,
        "exact_optimum": plan == optimum,
        "raw_utility_m": raw,
        "optimal_raw_utility_m": best,
        "raw_regret_m": best - raw,
        "decision_score": decision_score(values, substantive),
        "valid_submission": True,
        "organizational_failure": False,
        "failure_penalty": None,
        "penalty_is_scoring_convention": False,
    }


def score_organizational_failure(
        family: dict, rho: float) -> dict[str, float | str | bool | None]:
    """Apply the recorded worst-plan penalty to a failed organization cell.

    The imputed worst-plan utility supports unconditional analysis. It does not
    assert that the agents selected that plan; no valid company plan exists.
    """
    key = str(float(rho))
    values = family["utilities"][key]
    best = max(values.values())
    worst = min(values.values())
    return {
        "submitted_plan": None,
        "substantive_plan": None,
        "optimal_plan": family["labeled_optima"][key],
        "exact_optimum": False,
        "raw_utility_m": worst,
        "optimal_raw_utility_m": best,
        "raw_regret_m": best - worst,
        "decision_score": 0.0,
        "valid_submission": False,
        "organizational_failure": True,
        "failure_penalty": "worst_plan_within_family_rho",
        "penalty_is_scoring_convention": True,
    }
