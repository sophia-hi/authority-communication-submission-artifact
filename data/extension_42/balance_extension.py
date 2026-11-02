"""Balance 42 new families jointly with the unchanged original 60.

Eight choices per new family: two Lead sides x four A/B label mappings.
The mixed-integer program fixes one choice per new family and constrains
combined-panel margins. Existing family assignments are constants.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix
import yaml


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / "src"
sys.path.insert(0, str(SOURCE))

from generator import RHO_GRID, apply_label_map, relabel_family  # noqa: E402
from seed_design import acceptance_reasons, build_frame, validate_frame  # noqa: E402


def stratum(family: dict) -> tuple[str, float]:
    return (family["substantive_optima"]["1.0"],
            float(family["first_grid_switch_rho"]))


def maps_from_bits(branch1_a: int, branch2_a: int) -> list[dict[str, str]]:
    return [{"premium": "A" if bit else "B",
             "standard": "B" if bit else "A"}
            for bit in (branch1_a, branch2_a)]


def features(family: dict, maps: list[dict[str, str]], lead: int) -> Counter[tuple]:
    out: Counter[tuple] = Counter()
    key = stratum(family)
    out[("lead2",)] = int(lead == 1)
    out[("stratum_lead2", key)] = int(lead == 1)
    for branch in (0, 1):
        out[("premium_a", branch)] = int(maps[branch]["premium"] == "A")
    for rho in RHO_GRID:
        rho_key = str(rho)
        optimum = family["substantive_optima"][rho_key]
        answer = apply_label_map(optimum, maps)
        out[("answer", rho_key, answer)] = 1
        out[("stratum_answer", key, rho_key, answer)] = 1
        out[("role_a", rho_key, "Lead")] = int(answer[lead] == "A")
        out[("role_a", rho_key, "Reporting")] = int(answer[1 - lead] == "A")
        if rho == 1.0:
            out[("rho1_answer_lead", answer, lead)] = 1
        local = family["local_plan"].split("|")
        optimal = optimum.split("|")
        changed = [branch for branch in (0, 1) if local[branch] != optimal[branch]]
        if len(changed) == 1:
            role = "Lead" if changed[0] == lead else "Reporting"
            out[("giveway", rho_key, role)] = 1
            out[("giveway_direction", rho_key, role, optimal[changed[0]])] = 1
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path,
                        help="write regenerated assignments to a separate directory")
    args = parser.parse_args()
    if args.out_dir and args.out_dir.resolve() == HERE.resolve():
        parser.error("--out-dir must be separate from the archived assignment directory")
    config = yaml.safe_load((SOURCE / "config.yaml").read_text())
    original, original_audit = build_frame(config)
    validate_frame(original, original_audit, config)
    extension_data = json.loads((HERE / "extension_42_economic_families.json").read_text())
    new = extension_data["families"]
    assert len(original) == 60 and len(new) == 42
    assert all(not acceptance_reasons(family, config) for family in new)

    old_features: Counter[tuple] = Counter()
    for family in original:
        old_features.update(features(family, family["label_maps"],
                                     family["lead_branch_index"]))

    states: list[tuple[int, int, int, int]] = []
    state_features: list[Counter[tuple]] = []
    for family_index, family in enumerate(new):
        for lead in (0, 1):
            for first_a in (0, 1):
                for second_a in (0, 1):
                    states.append((family_index, lead, first_a, second_a))
                    state_features.append(features(family,
                        maps_from_bits(first_a, second_a), lead))
    variable_count = len(states)
    assert variable_count == 42 * 8
    constraints: list[tuple[str, tuple, int, int]] = []

    for index in range(42):
        constraints.append((f"one_state_{index}", ("one_state", index), 1, 1))

    def combined_target(name: str, key: tuple, lower: int, upper: int) -> None:
        constraints.append((name, key, lower - old_features[key],
                            upper - old_features[key]))

    combined_target("Lead Branch 2 total", ("lead2",), 51, 51)
    for key in sorted({stratum(family) for family in new}):
        combined_target(f"Lead Branch 2 in {key}",
                        ("stratum_lead2", key), 8, 9)
    for branch in (0, 1):
        combined_target(f"premium maps to A in branch {branch + 1}",
                        ("premium_a", branch), 51, 51)
    for rho in RHO_GRID:
        rho_key = str(rho)
        for answer in ("AA", "AB", "BA", "BB"):
            combined_target(f"rho {rho_key} answer {answer}",
                            ("answer", rho_key, answer), 24, 27)
        for role in ("Lead", "Reporting"):
            combined_target(f"rho {rho_key} role {role} A",
                            ("role_a", rho_key, role), 50, 52)
        for key in sorted({stratum(family) for family in new}):
            for answer in ("AA", "AB", "BA", "BB"):
                combined_target(f"rho {rho_key} stratum {key} answer {answer}",
                                ("stratum_answer", key, rho_key, answer), 3, 6)
    for answer in ("AA", "AB", "BA", "BB"):
        for lead in (0, 1):
            combined_target(f"rho 1 answer {answer} Lead side {lead}",
                            ("rho1_answer_lead", answer, lead), 12, 13)

    for rho in RHO_GRID[1:]:
        rho_key = str(rho)
        for direction in ("premium", "standard"):
            old_total = sum(old_features[("giveway_direction", rho_key, role, direction)]
                            for role in ("Lead", "Reporting"))
            new_total = 0
            for family in new:
                local = family["local_plan"].split("|")
                optimal = family["substantive_optima"][rho_key].split("|")
                changed = [branch for branch in (0, 1)
                           if local[branch] != optimal[branch]]
                new_total += len(changed) == 1 and optimal[changed[0]] == direction
            # All selected families have at most one branch changing on this
            # grid; direction is counted by the role-state features below.
            total = old_total + new_total
            combined_target(f"rho {rho_key} {direction} give-way Lead",
                            ("giveway_direction", rho_key, "Lead", direction),
                            total // 2, math.ceil(total / 2))

    stages = (
        set(),
        {"rho1_answer_lead"},
        {"giveway_direction"},
        {"rho1_answer_lead", "giveway_direction"},
        {"role_a"},
        {"role_a", "rho1_answer_lead"},
        {"role_a", "giveway_direction"},
        {"role_a", "rho1_answer_lead", "giveway_direction"},
    )
    if args.out_dir:
        rng = np.random.default_rng(20261027)
        objective = rng.uniform(0.0001, 0.001, variable_count)
        solution = None
        active_constraints = []
        relaxed = set()
        for relaxed in stages:
            active_constraints = [row for row in constraints if row[1][0] not in relaxed]
            matrix = lil_matrix((len(active_constraints), variable_count), dtype=float)
            lower = np.empty(len(active_constraints))
            upper = np.empty(len(active_constraints))
            for row_index, (_, key, lo, hi) in enumerate(active_constraints):
                lower[row_index], upper[row_index] = lo, hi
                for column_index, (family_index, _, _, _) in enumerate(states):
                    matrix[row_index, column_index] = (
                        int(family_index == key[1]) if key[0] == "one_state"
                        else state_features[column_index][key])
            print(f"solving {variable_count} binary states, {len(active_constraints)} constraints; relaxed={sorted(relaxed)}", flush=True)
            trial = milp(
                c=objective, integrality=np.ones(variable_count),
                bounds=Bounds(np.zeros(variable_count), np.ones(variable_count)),
                constraints=LinearConstraint(matrix.tocsr(), lower, upper),
                options={"time_limit": 45, "mip_rel_gap": 0.01},
            )
            print(f"MILP status {trial.status}: {trial.message}", flush=True)
            if trial.x is not None and trial.status in (0, 1):
                solution = trial
                break
        if solution is None:
            raise RuntimeError("No balance assignment found under tested constraints")
        # Within the feasible 24..27 bounds, minimize departures from the ideal
        # 25..26 answer-label counts. The original 60 assignments remain fixed.
        answer_keys = [("answer", str(rho), answer)
                       for rho in RHO_GRID
                       for answer in ("AA", "AB", "BA", "BB")]
        extra_variables = 2 * len(answer_keys)
        refined = lil_matrix((len(active_constraints) + extra_variables,
                              variable_count + extra_variables), dtype=float)
        refined[:len(active_constraints), :variable_count] = matrix
        refined_lower = np.concatenate((lower, np.full(extra_variables, -np.inf)))
        refined_upper = np.concatenate((upper, np.full(extra_variables, np.inf)))
        for index, key in enumerate(answer_keys):
            deficit_row = len(active_constraints) + 2 * index
            excess_row = deficit_row + 1
            for column in range(variable_count):
                value = state_features[column][key]
                refined[deficit_row, column] = value
                refined[excess_row, column] = value
            refined[deficit_row, variable_count + 2 * index] = 1
            refined[excess_row, variable_count + 2 * index + 1] = -1
            refined_lower[deficit_row] = 25 - old_features[key]
            refined_upper[excess_row] = 26 - old_features[key]
        refined_objective = np.concatenate((objective, np.ones(extra_variables)))
        refined_solution = milp(
            c=refined_objective,
            integrality=np.concatenate((np.ones(variable_count),
                                        np.zeros(extra_variables))),
            bounds=Bounds(np.zeros(variable_count + extra_variables),
                          np.ones(variable_count + extra_variables)),
            constraints=LinearConstraint(refined.tocsr(), refined_lower,
                                         refined_upper),
            options={"time_limit": 120, "mip_rel_gap": 0.01},
        )
        print(f"label refinement status {refined_solution.status}: {refined_solution.message}", flush=True)
        if refined_solution.x is not None and refined_solution.status in (0, 1):
            solution = refined_solution
        chosen = [index for index, value in enumerate(solution.x[:variable_count])
                  if value > 0.5]
        assert len(chosen) == 42

    else:
        # Validate the actual archived choices without relying on a new solver run.
        saved_audit = json.loads((HERE / "combined_102_balance_audit.json").read_text())
        saved = json.loads((HERE / "extension_42_assignment.json").read_text())
        rows = saved["assignments"]
        if len(rows) != 42:
            raise ValueError("archived assignment must contain exactly 42 families")
        relaxed = set(saved_audit["relaxed_constraint_families"])
        if relaxed not in stages:
            raise ValueError("unknown archived constraint relaxation")
        active_constraints = [row for row in constraints if row[1][0] not in relaxed]
        state_index = {state: index for index, state in enumerate(states)}
        chosen = []
        for i, row in enumerate(rows):
            if row["family_id"] != 61 + i or row["candidate_id"] != new[i]["candidate_id"]:
                raise ValueError("archived family or candidate identity mismatch")
            labels = (row["branch1_premium_label"], row["branch2_premium_label"])
            if row["lead_branch_index"] not in (0, 1) or any(x not in ("A", "B") for x in labels):
                raise ValueError("invalid archived role or label")
            chosen.append(state_index[(i, row["lead_branch_index"],
                                       int(labels[0] == "A"), int(labels[1] == "A"))])
        solution = SimpleNamespace(message=saved_audit["solver_status"])

    assigned = []
    certificate = []
    for index in chosen:
        family_index, lead, first_a, second_a = states[index]
        family = new[family_index]
        maps = maps_from_bits(first_a, second_a)
        row = relabel_family(family, maps)
        row["family_id"] = 61 + family_index
        row["lead_branch_index"] = lead
        row["reporting_branch_index"] = 1 - lead
        row["document_template_seed"] = config["document_template_seed"]
        row["counterbalance_seed"] = 20261027
        row["design_version"] = config["design_version"]
        assigned.append(row)
        certificate.append({
            "family_id": 61 + family_index,
            "candidate_id": family["candidate_id"],
            "lead_branch_index": lead,
            "branch1_premium_label": maps[0]["premium"],
            "branch2_premium_label": maps[1]["premium"],
            "economic_stratum": {"substantive_rho1_optimum": stratum(family)[0],
                                 "first_switch_rho": stratum(family)[1]},
        })
    assigned.sort(key=lambda row: row["family_id"])
    certificate.sort(key=lambda row: row["family_id"])

    full = original + assigned
    combined: Counter[tuple] = Counter()
    for family in full:
        combined.update(features(family, family["label_maps"],
                                 family["lead_branch_index"]))
    violations = [(name, combined[key], lo + old_features[key], hi + old_features[key])
                  for name, key, lo, hi in active_constraints if key[0] != "one_state"
                  and not (lo + old_features[key] <= combined[key] <= hi + old_features[key])]
    assert not violations, violations[:5]
    assert [family["candidate_id"] for family in full[:60]] == [
        family["candidate_id"] for family in original]
    for family in full:
        sequence = [family["substantive_optima"][str(rho)] for rho in RHO_GRID]
        assert sequence[0] == family["local_plan"]
        assert sequence[-1] != sequence[0]
        assert sum(left != right for left, right in zip(sequence, sequence[1:])) == 1
        assert not acceptance_reasons(family, config)

    audit = {
        "label": "exploratory_extension_42_plus_unchanged_60",
        "original_families": 60,
        "new_families": 42,
        "combined_families": 102,
        "potential_cells_if_all_7_orgs_x_5_rho_run": 3570,
        "selected_candidate_ids": [family["candidate_id"] for family in assigned],
        "source_original_counterbalance_sha256": hashlib.sha256(
            (SOURCE / "counterbalance_assignment.json").read_bytes()).hexdigest(),
        "original_audit": original_audit,
        "balance_constraint_count": len(active_constraints) - 42,
        "relaxed_constraint_families": sorted(relaxed),
        "solver_status": solution.message,
        "economic_strata": {
            f"{end}__switch_{switch}": sum(stratum(family) == (end, switch)
                                            for family in full)
            for end, switch in sorted({stratum(family) for family in full})},
        "rho1_substantive_optimum_counts": dict(Counter(
            family["substantive_optima"]["1.0"] for family in full)),
        "first_switch_counts": dict(Counter(
            str(family["first_grid_switch_rho"]) for family in full)),
        "minimum_optimum_margin_m": min(
            min(family["optimum_margins_m"].values()) for family in full),
        "minimum_relative_optimum_margin": min(
            min(family["relative_optimum_margins"].values()) for family in full),
        "lead_branch_2_count": combined[("lead2",)],
        "premium_maps_to_A_by_branch": {
            str(branch + 1): combined[("premium_a", branch)]
            for branch in (0, 1)},
        "answer_label_counts_by_rho": {
            str(rho): {answer: combined[("answer", str(rho), answer)]
                       for answer in ("AA", "AB", "BA", "BB")}
            for rho in RHO_GRID},
        "role_A_counts_by_rho": {
            str(rho): {role: combined[("role_a", str(rho), role)]
                       for role in ("Lead", "Reporting")}
            for rho in RHO_GRID},
        "giveway_by_rho": {
            str(rho): {role: combined[("giveway", str(rho), role)]
                       for role in ("Lead", "Reporting")}
            for rho in RHO_GRID},
        "giveway_direction_by_rho": {
            str(rho): {role: {direction: combined[("giveway_direction", str(rho), role, direction)]
                               for direction in ("premium", "standard")}
                       for role in ("Lead", "Reporting")}
            for rho in RHO_GRID},
        "rho1_answer_by_lead_side": {
            answer: {str(lead + 1): combined[("rho1_answer_lead", answer, lead)]
                     for lead in (0, 1)}
            for answer in ("AA", "AB", "BA", "BB")},
    }
    generated = {
        "extension_42_assignment.json":
            {"label": audit["label"], "assignments": certificate},
        "extension_42_assigned_families.json":
            {"label": audit["label"], "families": assigned},
        "combined_102_assigned_families.json":
            {"label": audit["label"], "families": full},
        "combined_102_balance_audit.json": audit,
    }
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in generated.items():
            (args.out_dir / name).write_text(json.dumps(payload, indent=2) + "\n")
    else:
        for name, payload in generated.items():
            archived = json.loads((HERE / name).read_text())
            if name == "combined_102_balance_audit.json":
                # The archived hash identifies the collection-time certificate;
                # the current certificate is separately validated above.
                historical_hash = archived["original_audit"]["counterbalance"]["reproducibility_sha256"]
                if historical_hash != "26ab61f80d1c9438619ed5f6f12222e9b13cc70b5b85f33bb13eabe278c5550f":
                    raise ValueError("unexpected collection-time certificate hash")
                payload["original_audit"]["counterbalance"]["reproducibility_sha256"] = historical_hash
            if archived != payload:
                raise ValueError(f"archived assignment or balance audit differs from {name}")
        print("Verified archived 42-family assignment, active constraints, and combined balance audit")
    print(json.dumps({key: audit[key] for key in (
        "economic_strata", "lead_branch_2_count", "premium_maps_to_A_by_branch",
        "answer_label_counts_by_rho", "giveway_direction_by_rho")}, indent=2), flush=True)


if __name__ == "__main__":
    main()
