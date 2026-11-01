"""Transparent two-branch pricing environment.

All random primitives come from a SHA-256 counter stream.  The economics are
stored before A/B relabeling so an audit can distinguish substantive policies
from arbitrary answer labels.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
from typing import Iterable


ECONOMIC_GENERATOR_VERSION = "branch_pricing_v1"
SUBSTANTIVE_ACTIONS = ("standard", "premium")
LABELS = ("A", "B")
RHO_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)


class AuditRNG:
    """Counter-based deterministic draws with no global RNG state."""

    def __init__(self, master_seed: int, candidate_id: int):
        self.key = (
            f"{ECONOMIC_GENERATOR_VERSION}|{master_seed}|{candidate_id}"
        ).encode()
        self.index = 0

    def _u01(self) -> float:
        payload = self.key + b"|" + str(self.index).encode()
        self.index += 1
        raw = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
        return (raw + 0.5) / 2**64

    def uniform(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self._u01()

    def normal(self, mean: float, sd: float) -> float:
        u1 = max(self._u01(), 1e-15)
        u2 = self._u01()
        z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2 * math.pi * u2)
        return mean + sd * z


@dataclass(frozen=True)
class BranchPrimitives:
    base_units: float
    reference_price: float
    elasticity: float
    seasonal_index: float
    availability: float
    standard_price_change: float
    premium_price_change: float
    standard_discount: float
    premium_discount: float
    return_rate: float
    landed_unit_cost: float
    fulfillment_unit_cost: float
    warranty_rate: float
    standard_fixed_cost: float
    premium_fixed_cost: float


def _branch(rng: AuditRNG) -> BranchPrimitives:
    # The same distributions and calculation graph are used for both branches.
    reference_price = rng.uniform(88.0, 132.0)
    landed = rng.uniform(35.0, 58.0)
    return BranchPrimitives(
        base_units=rng.uniform(105_000.0, 185_000.0),
        reference_price=reference_price,
        elasticity=rng.uniform(-2.35, -0.75),
        seasonal_index=rng.uniform(0.94, 1.09),
        availability=rng.uniform(0.91, 0.99),
        standard_price_change=rng.uniform(-0.045, -0.005),
        premium_price_change=rng.uniform(0.045, 0.115),
        standard_discount=rng.uniform(0.045, 0.095),
        premium_discount=rng.uniform(0.025, 0.070),
        return_rate=rng.uniform(0.035, 0.085),
        landed_unit_cost=landed,
        fulfillment_unit_cost=rng.uniform(5.0, 10.0),
        warranty_rate=rng.uniform(0.008, 0.022),
        standard_fixed_cost=rng.uniform(0.10, 0.38),
        premium_fixed_cost=rng.uniform(0.28, 0.78),
    )


def local_table(p: BranchPrimitives) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for action in SUBSTANTIVE_ACTIONS:
        change = getattr(p, f"{action}_price_change")
        discount = getattr(p, f"{action}_discount")
        fixed = getattr(p, f"{action}_fixed_cost")
        price = p.reference_price * (1.0 + change)
        demand_factor = max(0.35, 1.0 + p.elasticity * change)
        units = p.base_units * p.seasonal_index * p.availability * demand_factor
        realized_price = price * (1.0 - discount)
        net_kept_units = units * (1.0 - p.return_rate)
        warranty = price * p.warranty_rate
        unit_cost = p.landed_unit_cost + p.fulfillment_unit_cost + warranty
        contribution_m = net_kept_units * (realized_price - unit_cost) / 1_000_000
        profit_m = contribution_m - fixed
        out[action] = {
            "price": price,
            "units": units,
            "realized_price": realized_price,
            "unit_cost": unit_cost,
            "unit_margin": realized_price - unit_cost,
            "fixed_cost_m": fixed,
            "profit_m": profit_m,
        }
    return out


def _interaction_primitives(rng: AuditRNG) -> dict[str, float]:
    # A log-uniform market-integration draw creates economically plausible
    # families whose coordination crossover occurs throughout the rho grid.
    log_scale = rng.uniform(math.log(0.12), math.log(1.50))
    return {
        "market_integration_index": math.exp(log_scale),
        "coherence_bonus_per_unit": rng.uniform(1.25, 4.50),
        "mismatch_penalty_per_unit": rng.uniform(2.50, 7.50),
        "migration_rate": rng.uniform(0.025, 0.085),
        "premium_campaign_synergy_m": rng.uniform(0.20, 1.15),
        "standard_service_synergy_m": rng.uniform(0.05, 0.55),
    }


def interaction_table(local: list[dict], interaction: dict) -> dict[str, float]:
    table: dict[str, float] = {}
    for a1 in SUBSTANTIVE_ACTIONS:
        for a2 in SUBSTANTIVE_ACTIONS:
            x1, x2 = local[0][a1], local[1][a2]
            combined_units = x1["units"] + x2["units"]
            if a1 == a2:
                value = (interaction["coherence_bonus_per_unit"]
                         * combined_units / 1_000_000)
                value += (interaction["premium_campaign_synergy_m"]
                          if a1 == "premium"
                          else interaction["standard_service_synergy_m"])
            else:
                penalty = (interaction["mismatch_penalty_per_unit"]
                           * combined_units / 1_000_000)
                # Customers migrate from the higher posted price to the lower.
                if x1["price"] >= x2["price"]:
                    high, low = x1, x2
                else:
                    high, low = x2, x1
                shifted = interaction["migration_rate"] * high["units"]
                migration_effect = shifted * (
                    low["unit_margin"] - high["unit_margin"]) / 1_000_000
                value = -penalty + migration_effect
            table[f"{a1}|{a2}"] = (
                interaction["market_integration_index"] * value)
    return table


def utility_table(local: list[dict], interaction: dict[str, float], rho: float
                  ) -> dict[str, float]:
    return {
        f"{a1}|{a2}": (local[0][a1]["profit_m"]
                        + local[1][a2]["profit_m"]
                        + rho * interaction[f"{a1}|{a2}"])
        for a1 in SUBSTANTIVE_ACTIONS for a2 in SUBSTANTIVE_ACTIONS
    }


def unique_argmax(values: dict[str, float], tol: float = 1e-9) -> str | None:
    ranked = sorted(values.items(), key=lambda kv: kv[1], reverse=True)
    if len(ranked) > 1 and ranked[0][1] - ranked[1][1] <= tol:
        return None
    return ranked[0][0]


def optimum_margin(values: dict[str, float]) -> float:
    ranked = sorted(values.values(), reverse=True)
    return ranked[0] - ranked[1]


def relative_optimum_margin(values: dict[str, float]) -> float:
    """Best-versus-runner-up gap as a share of absolute best profit."""
    ranked = sorted(values.values(), reverse=True)
    denominator = abs(ranked[0])
    if denominator == 0.0:
        return math.inf if ranked[0] > ranked[1] else 0.0
    return (ranked[0] - ranked[1]) / denominator


def decision_score(values: dict[str, float], plan: str) -> float:
    lo, hi = min(values.values()), max(values.values())
    if hi <= lo:
        return 100.0
    return 100.0 * (values[plan] - lo) / (hi - lo)


def generate_candidate(master_seed: int, candidate_id: int) -> dict:
    rng = AuditRNG(master_seed, candidate_id)
    primitives = [_branch(rng), _branch(rng)]
    local = [local_table(x) for x in primitives]
    interaction_primitives = _interaction_primitives(rng)
    w = interaction_table(local, interaction_primitives)
    utilities = {str(rho): utility_table(local, w, rho) for rho in RHO_GRID}
    optima = {rho: unique_argmax(utilities[str(rho)]) for rho in RHO_GRID}
    local_actions = [
        max(SUBSTANTIVE_ACTIONS, key=lambda a: local[i][a]["profit_m"])
        for i in range(2)
    ]
    local_plan = "|".join(local_actions)
    gaps = [abs(x["premium"]["profit_m"] - x["standard"]["profit_m"])
            for x in local]
    rho1 = utilities["1.0"]
    rho1_opt = optima[1.0]
    regret = (rho1[rho1_opt] - rho1[local_plan]) if rho1_opt else 0.0
    first_switch = next(
        (rho for rho in RHO_GRID if optima[rho] != local_plan), None)
    optimum_margins = {
        str(rho): optimum_margin(utilities[str(rho)]) for rho in RHO_GRID}
    relative_optimum_margins = {
        str(rho): relative_optimum_margin(utilities[str(rho)])
        for rho in RHO_GRID}
    local_plan_scores = {
        str(rho): decision_score(utilities[str(rho)], local_plan)
        for rho in RHO_GRID
    }
    return {
        "economic_generator_version": ECONOMIC_GENERATOR_VERSION,
        "master_seed": int(master_seed),
        "candidate_id": int(candidate_id),
        "rng_draws": rng.index,
        "branch_primitives": [asdict(x) for x in primitives],
        "local": local,
        "interaction_primitives": interaction_primitives,
        "interaction": w,
        "utilities": utilities,
        "substantive_optima": {str(k): v for k, v in optima.items()},
        "local_plan": local_plan,
        "local_gaps_m": gaps,
        "rho1_regret_of_local_plan_m": regret,
        "first_grid_switch_rho": first_switch,
        "optimum_margins_m": optimum_margins,
        "relative_optimum_margins": relative_optimum_margins,
        "local_plan_scores": local_plan_scores,
    }


def apply_label_map(plan: str, maps: list[dict[str, str]]) -> str:
    return "".join(maps[i][a] for i, a in enumerate(plan.split("|")))


def relabel_family(family: dict, maps: list[dict[str, str]]) -> dict:
    result = dict(family)
    result["label_maps"] = maps
    result["labeled_optima"] = {
        rho: apply_label_map(plan, maps)
        for rho, plan in family["substantive_optima"].items()
    }
    result["labeled_local_plan"] = apply_label_map(family["local_plan"], maps)
    return result


def all_label_maps() -> Iterable[list[dict[str, str]]]:
    normal = {"standard": "A", "premium": "B"}
    flipped = {"standard": "B", "premium": "A"}
    for left in (normal, flipped):
        for right in (normal, flipped):
            yield [dict(left), dict(right)]
