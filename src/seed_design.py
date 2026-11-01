"""Select and audit the balanced 60-family exploratory frame."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from itertools import combinations
import json
from pathlib import Path

import yaml

from generator import RHO_GRID, generate_candidate, relabel_family


HERE = Path(__file__).resolve().parent
COUNTERBALANCE_FILE = HERE / "counterbalance_assignment.json"
LABEL_ASSIGNMENT_FILE = HERE / "label_assignment_v1.json"
COUNTERBALANCE_REPRODUCIBILITY_FILE = (
    HERE / "counterbalance_reproducibility_v19.json")
ANSWER_LABELS = ("AA", "AB", "BA", "BB")


def acceptance_reasons(family: dict, cfg: dict) -> list[str]:
    s = cfg["selection"]
    reasons: list[str] = []
    if any(x < s["minimum_local_gap_m"] for x in family["local_gaps_m"]):
        reasons.append("local_gap_too_small")
    if any(x > s["maximum_local_gap_m"] for x in family["local_gaps_m"]):
        reasons.append("local_gap_too_large")
    optima = family["substantive_optima"]
    if any(optima[str(rho)] is None for rho in RHO_GRID):
        reasons.append("nonunique_optimum")
    if any(x < s["minimum_optimum_margin_m"]
           for x in family["optimum_margins_m"].values()):
        reasons.append("optimum_margin_too_small")
    if any(x < s["minimum_relative_optimum_margin"]
           for x in family["relative_optimum_margins"].values()):
        reasons.append("relative_optimum_margin_too_small")
    if optima["0.0"] != family["local_plan"]:
        reasons.append("rho0_not_local_plan")
    if optima["1.0"] == family["local_plan"]:
        reasons.append("rho1_no_coordination_change")
    if (family["rho1_regret_of_local_plan_m"]
            < s["minimum_rho1_regret_of_local_plan_m"]):
        reasons.append("rho1_change_not_material")
    switch = family["first_grid_switch_rho"]
    if switch is None or not (
            s["transition_rho_min"] <= switch <= s["transition_rho_max"]):
        reasons.append("transition_outside_target")
    elif (100.0 - family["local_plan_scores"][str(switch)]
          < s["minimum_adjacent_score_change"]):
        reasons.append("transition_not_material_on_score")
    return reasons


def _stratum_key(family: dict) -> str:
    return (f"{family['substantive_optima']['1.0']}"
            f"__switch_{float(family['first_grid_switch_rho']):g}")


def _maps_from_assignment(row: dict) -> list[dict[str, str]]:
    maps = []
    for branch in (1, 2):
        premium = row[f"branch{branch}_premium_label"]
        if premium not in {"A", "B"}:
            raise ValueError("counterbalance premium label must be A or B")
        maps.append({
            "premium": premium,
            "standard": "B" if premium == "A" else "A",
        })
    return maps


def _load_counterbalance(frame: list[dict], cfg: dict) -> tuple[list[dict], dict]:
    raw = COUNTERBALANCE_FILE.read_bytes()
    certificate = json.loads(raw)
    label_raw = LABEL_ASSIGNMENT_FILE.read_bytes()
    label_certificate = json.loads(label_raw)
    if label_certificate.get("version") != "label_assignment_v1":
        raise ValueError("unexpected label-assignment version")
    computed_label_maps_sha256 = hashlib.sha256(json.dumps(
        label_certificate.get("assignments", []), sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    if label_certificate.get("label_maps_sha256") \
            != computed_label_maps_sha256:
        raise ValueError("frozen label-assignment content hash mismatch")
    label_by_candidate = {
        int(row["candidate_id"]): row
        for row in label_certificate.get("assignments", [])}
    if certificate["algorithm_version"] != "seeded_constrained_counterbalance_v2":
        raise ValueError("unexpected counterbalance algorithm version")
    if int(certificate["counterbalance_seed"]) != int(cfg["counterbalance_seed"]):
        raise ValueError("counterbalance seed does not match config")
    assignments = certificate["assignments"]
    if len(assignments) != len(frame):
        raise ValueError("counterbalance assignment has the wrong family count")
    by_candidate = {int(row["candidate_id"]): row for row in assignments}
    if len(by_candidate) != len(assignments):
        raise ValueError("counterbalance candidate IDs are not unique")

    assigned = []
    for family_id, source in enumerate(frame, 1):
        candidate_id = int(source["candidate_id"])
        if candidate_id not in by_candidate:
            raise ValueError(f"candidate {candidate_id} is absent from counterbalance assignment")
        row = by_candidate[candidate_id]
        label_row = label_by_candidate.get(candidate_id)
        if not label_row or any(
                row[f"branch{branch}_premium_label"]
                != label_row[f"branch{branch}_premium_label"]
                for branch in (1, 2)):
            raise ValueError("counterbalance labels differ from frozen label assignment")
        expected_stratum = {
            "substantive_rho1_optimum": source["substantive_optima"]["1.0"],
            "first_switch_rho": source["first_grid_switch_rho"],
        }
        if row["economic_stratum"] != expected_stratum:
            raise ValueError("counterbalance economic stratum mismatch")
        if int(row["family_id"]) != family_id:
            raise ValueError("counterbalance family order mismatch")
        lead = int(row["lead_branch_index"])
        if lead not in (0, 1):
            raise ValueError("counterbalance Lead branch must be zero or one")
        family = relabel_family(source, _maps_from_assignment(row))
        family["family_id"] = family_id
        family["lead_branch_index"] = lead
        family["reporting_branch_index"] = 1 - lead
        family["document_template_seed"] = int(cfg["document_template_seed"])
        family["counterbalance_seed"] = int(cfg["counterbalance_seed"])
        assigned.append(family)
    metadata = {
        "algorithm_version": certificate["algorithm_version"],
        "counterbalance_seed": int(certificate["counterbalance_seed"]),
        "assignment_sha256": hashlib.sha256(raw).hexdigest(),
        "label_assignment_file": LABEL_ASSIGNMENT_FILE.name,
        "label_assignment_sha256": hashlib.sha256(label_raw).hexdigest(),
        "label_maps_sha256": label_certificate["label_maps_sha256"],
        "reproducibility_file": COUNTERBALANCE_REPRODUCIBILITY_FILE.name,
        "reproducibility_sha256": hashlib.sha256(
            COUNTERBALANCE_REPRODUCIBILITY_FILE.read_bytes()).hexdigest(),
        "selection_rule": certificate["selection_rule"],
        "hard_constraints": certificate["hard_constraints"],
    }
    return assigned, metadata


def _give_way_role(family: dict, rho: float) -> str:
    local = family["local_plan"].split("|")
    optimum = family["substantive_optima"][str(rho)].split("|")
    changed = [index for index in (0, 1) if local[index] != optimum[index]]
    if not changed:
        return "neither"
    if len(changed) == 2:
        return "both"
    return "Lead" if changed[0] == family["lead_branch_index"] else "Reporting"


def _give_way_direction(family: dict, rho: float) -> str:
    local = family["local_plan"].split("|")
    optimum = family["substantive_optima"][str(rho)].split("|")
    changed = [index for index in (0, 1) if local[index] != optimum[index]]
    if len(changed) != 1:
        return "not_single_role"
    return optimum[changed[0]]


def minimum_give_way_imbalance(frame: list[dict], rho: float) -> int:
    """Minimum |Lead-Reporting| with five Lead sides per economic stratum."""
    possible_totals = {0}
    for stratum in sorted({_stratum_key(family) for family in frame}):
        indices = [
            index for index, family in enumerate(frame)
            if _stratum_key(family) == stratum]
        contributions = set()
        for branch_2_lead_indices in combinations(indices, 5):
            branch_2_lead = set(branch_2_lead_indices)
            lead_gives = 0
            for index in indices:
                family = frame[index]
                local = family["local_plan"].split("|")
                optimum = family["substantive_optima"][str(rho)].split("|")
                changed = [branch for branch in (0, 1)
                           if local[branch] != optimum[branch]]
                if len(changed) != 1:
                    continue
                lead_branch = 1 if index in branch_2_lead else 0
                lead_gives += changed[0] == lead_branch
            contributions.add(lead_gives)
        possible_totals = {
            previous + contribution
            for previous in possible_totals for contribution in contributions}
    single_role_total = 0
    for family in frame:
        local = family["local_plan"].split("|")
        optimum = family["substantive_optima"][str(rho)].split("|")
        single_role_total += sum(
            local[branch] != optimum[branch] for branch in (0, 1)) == 1
    return min(abs(2 * lead_gives - single_role_total)
               for lead_gives in possible_totals)


def counterbalance_audit(frame: list[dict], metadata: dict) -> dict:
    mapping_counts = {}
    for branch in (0, 1):
        counts = Counter(f["label_maps"][branch]["premium"] for f in frame)
        mapping_counts[f"branch_{branch + 1}_premium_label"] = {
            label: counts[label] for label in ("A", "B")}

    lead_by_stratum = {}
    for key in sorted({_stratum_key(f) for f in frame}):
        counts = Counter(
            f["lead_branch_index"] + 1 for f in frame
            if _stratum_key(f) == key)
        lead_by_stratum[key] = {
            "branch_1": counts[1], "branch_2": counts[2]}

    correct_by_role = {}
    label_by_rho = {}
    label_by_stratum_and_lead = {}
    give_way = {}
    give_way_by_direction = {}
    for rho in RHO_GRID:
        rho_key = str(rho)
        role_counts = {role: Counter() for role in ("Lead", "Reporting")}
        labels = Counter()
        nested = {}
        for family in frame:
            answer = family["labeled_optima"][rho_key]
            labels[answer] += 1
            lead = family["lead_branch_index"]
            role_counts["Lead"][answer[lead]] += 1
            role_counts["Reporting"][answer[1 - lead]] += 1
            stratum = _stratum_key(family)
            lead_key = f"lead_branch_{lead + 1}"
            nested.setdefault(stratum, {}).setdefault(lead_key, Counter())[answer] += 1
        correct_by_role[rho_key] = {
            role: {label: role_counts[role][label] for label in ("A", "B")}
            for role in ("Lead", "Reporting")}
        label_by_rho[rho_key] = {label: labels[label] for label in ANSWER_LABELS}
        label_by_stratum_and_lead[rho_key] = {
            stratum: {
                lead_key: {label: counts[label] for label in ANSWER_LABELS}
                for lead_key, counts in lead_groups.items()
            }
            for stratum, lead_groups in sorted(nested.items())
        }
        roles = Counter(_give_way_role(family, rho) for family in frame)
        give_way[rho_key] = {
            role: roles[role] for role in ("Lead", "Reporting", "both", "neither")}
        give_way_by_direction[rho_key] = {
            role: {
                direction: sum(
                    _give_way_role(family, rho) == role
                    and _give_way_direction(family, rho) == direction
                    for family in frame)
                for direction in ("premium", "standard")
            }
            for role in ("Lead", "Reporting")
        }

    rho1_by_lead = {}
    for label in ANSWER_LABELS:
        counts = Counter(
            f["lead_branch_index"] + 1 for f in frame
            if f["labeled_optima"]["1.0"] == label)
        rho1_by_lead[label] = {
            "lead_branch_1": counts[1], "lead_branch_2": counts[2]}

    return {
        **metadata,
        "label_mapping_counts": mapping_counts,
        "lead_branch_counts_by_economic_stratum": lead_by_stratum,
        "correct_answer_label_by_role_and_rho": correct_by_role,
        "answer_label_counts_by_rho": label_by_rho,
        "answer_labels_by_rho_stratum_and_lead_side": label_by_stratum_and_lead,
        "rho1_answer_label_by_lead_side": rho1_by_lead,
        "give_way_role_by_rho": give_way,
        "give_way_role_by_direction_and_rho": give_way_by_direction,
        "minimum_feasible_give_way_imbalance_by_rho": {
            str(rho): minimum_give_way_imbalance(frame, rho)
            for rho in RHO_GRID},
    }


def select_economic_families(cfg: dict) -> tuple[list[dict], Counter[str], int]:
    """Select and interleave the 60 substantive families before labels/roles."""
    # Cross the substantive coordinated policy with the first rho grid point
    # at which coordination changes the optimum: 2 x 3 x 10 = 60 families.
    stratum_quota = {
        (substantive, float(switch)): 10
        for substantive in cfg["target_substantive_rho1"]
        for switch in cfg["target_transition_rho"]
    }
    strata: dict[tuple[str, float], list[dict]] = {
        key: [] for key in stratum_quota}
    rejection_counts: Counter[str] = Counter()
    candidate_id = int(cfg["selection"]["candidate_start"])
    economic_master_seed = int(cfg["economic_master_seed"])
    while any(len(strata[k]) < stratum_quota[k] for k in strata):
        family = generate_candidate(economic_master_seed, candidate_id)
        candidate_id += 1
        reasons = acceptance_reasons(family, cfg)
        if reasons:
            rejection_counts.update(reasons)
            continue
        key = (family["substantive_optima"]["1.0"],
               float(family["first_grid_switch_rho"]))
        if key not in strata or len(strata[key]) >= stratum_quota[key]:
            rejection_counts.update(["filled_or_unplanned_stratum"])
            continue
        strata[key].append(family)

    # Interleave the six economic strata. A separately seeded, frozen
    # assignment certificate can then counterbalance arbitrary A/B maps and
    # Lead sides without changing which economic candidates enter the frame.
    ordered_keys = sorted(strata, key=lambda x: (x[1], x[0]))
    accepted = [strata[key][slot] for slot in range(10) for key in ordered_keys]
    return accepted, rejection_counts, candidate_id


def build_frame(cfg: dict) -> tuple[list[dict], dict]:
    accepted, rejection_counts, candidate_id = select_economic_families(cfg)
    for family in accepted:
        family["design_version"] = str(cfg["design_version"])
        if family.get("economic_generator_version") != str(
                cfg["economic_generator_version"]):
            raise ValueError("economic generator version does not match config")
    accepted, counterbalance_metadata = _load_counterbalance(accepted, cfg)
    balance = counterbalance_audit(accepted, counterbalance_metadata)
    audit = {
        "design_version": cfg["design_version"],
        "master_seed": int(cfg["economic_master_seed"]),
        "document_template_seed": int(cfg["document_template_seed"]),
        "candidate_ids_scanned": candidate_id - cfg["selection"]["candidate_start"],
        "accepted": len(accepted),
        "minimum_relative_optimum_margin": float(
            cfg["selection"]["minimum_relative_optimum_margin"]),
        "rejection_reason_counts": dict(sorted(rejection_counts.items())),
        "rho1_label_counts": dict(Counter(
            f["labeled_optima"]["1.0"] for f in accepted)),
        "lead_branch_counts": dict(Counter(
            str(f["lead_branch_index"] + 1) for f in accepted)),
        "substantive_rho1_counts": dict(Counter(
            f["substantive_optima"]["1.0"] for f in accepted)),
        "local_plan_counts": dict(Counter(f["local_plan"] for f in accepted)),
        "switch_rho_counts": dict(Counter(
            str(f["first_grid_switch_rho"]) for f in accepted)),
        "counterbalance": balance,
    }
    return accepted, audit


def validate_frame(frame: list[dict], audit: dict, cfg: dict) -> None:
    assert len(frame) == int(cfg["families"])
    assert audit["rho1_label_counts"] == {
        k: int(v) for k, v in cfg["target_rho1_labels"].items()}
    assert audit["lead_branch_counts"] == {"1": 30, "2": 30}
    assert audit["switch_rho_counts"] == {
        str(float(k)): int(v) for k, v in cfg["target_transition_rho"].items()}
    assert audit["substantive_rho1_counts"] == {
        k: int(v) for k, v in cfg["target_substantive_rho1"].items()}
    assert len({f["candidate_id"] for f in frame}) == len(frame)
    for f in frame:
        assert f["design_version"] == cfg["design_version"]
        assert f["economic_generator_version"] == cfg[
            "economic_generator_version"]
        assert not acceptance_reasons(f, cfg)
        assert all(
            f["relative_optimum_margins"][str(rho)]
            >= float(cfg["selection"]["minimum_relative_optimum_margin"])
            for rho in RHO_GRID)
    balance = audit["counterbalance"]
    assert balance["label_assignment_sha256"] == hashlib.sha256(
        LABEL_ASSIGNMENT_FILE.read_bytes()).hexdigest()
    for counts in balance["label_mapping_counts"].values():
        assert counts == {"A": 30, "B": 30}
    for counts in balance["lead_branch_counts_by_economic_stratum"].values():
        assert counts == {"branch_1": 5, "branch_2": 5}
    for rho in RHO_GRID:
        rho_key = str(rho)
        for role in ("Lead", "Reporting"):
            assert 29 <= balance["correct_answer_label_by_role_and_rho"][rho_key][role]["A"] <= 31
        for count in balance["answer_label_counts_by_rho"][rho_key].values():
            assert 14 <= count <= 16
        for lead_groups in balance[
                "answer_labels_by_rho_stratum_and_lead_side"][rho_key].values():
            for counts in lead_groups.values():
                assert set(counts.values()) <= {1, 2}
        give_way = balance["give_way_role_by_rho"][rho_key]
        assert abs(give_way["Lead"] - give_way["Reporting"]) == (
            balance["minimum_feasible_give_way_imbalance_by_rho"][rho_key])
    assert balance["answer_label_counts_by_rho"]["1.0"] == {
        label: 15 for label in ANSWER_LABELS}
    for counts in balance["rho1_answer_label_by_lead_side"].values():
        assert sorted(counts.values()) == [7, 8]
    rho1_give_way = balance["give_way_role_by_rho"]["1.0"]
    assert abs(rho1_give_way["Lead"] - rho1_give_way["Reporting"]) == (
        balance["minimum_feasible_give_way_imbalance_by_rho"]["1.0"])
    assert balance["give_way_role_by_direction_and_rho"] == {
        "0.0": {
            "Lead": {"premium": 0, "standard": 0},
            "Reporting": {"premium": 0, "standard": 0}},
        "0.25": {
            "Lead": {"premium": 6, "standard": 5},
            "Reporting": {"premium": 4, "standard": 5}},
        "0.5": {
            "Lead": {"premium": 9, "standard": 11},
            "Reporting": {"premium": 11, "standard": 9}},
        "0.75": {
            "Lead": {"premium": 15, "standard": 15},
            "Reporting": {"premium": 15, "standard": 15}},
        "1.0": {
            "Lead": {"premium": 15, "standard": 15},
            "Reporting": {"premium": 15, "standard": 15}},
    }
    reproducibility = json.loads(
        COUNTERBALANCE_REPRODUCIBILITY_FILE.read_text(encoding="utf-8"))
    canonical = lambda value: hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    logical_assignment = [{
        "candidate_id": family["candidate_id"],
        "label_maps": family["label_maps"],
        "lead_branch_index": family["lead_branch_index"],
    } for family in frame]
    assert reproducibility["design_version"] == cfg["design_version"]
    assert reproducibility["economic_generator_version"] == cfg[
        "economic_generator_version"]
    assert reproducibility["counterbalance_seed"] == cfg[
        "counterbalance_seed"]
    assert reproducibility["label_assignment_sha256"] == hashlib.sha256(
        LABEL_ASSIGNMENT_FILE.read_bytes()).hexdigest()
    assert reproducibility[
        "lead_assignment_certificate_sha256"] == hashlib.sha256(
            COUNTERBALANCE_FILE.read_bytes()).hexdigest()
    assert reproducibility["new_frame_sha256"] == canonical(frame)
    assert reproducibility["new_assignment_logical_sha256"] == canonical(
        logical_assignment)
    assert reproducibility["tie_break"] == "first feasible assignment"
    assert reproducibility["hard_constraints_validation"] == "passed"
    assert reproducibility["targets"] == {
        rho: balance["give_way_role_by_direction_and_rho"][rho]
        for rho in ("0.25", "0.5", "0.75", "1.0")
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", type=Path,
                   help="write regenerated frame and audit to a separate directory")
    args = p.parse_args()
    cfg = yaml.safe_load((HERE / "config.yaml").read_text())
    frame, audit = build_frame(cfg)
    validate_frame(frame, audit, cfg)
    print(json.dumps(audit, indent=2, sort_keys=True))
    if args.out_dir:
        out = args.out_dir
        out.mkdir(parents=True, exist_ok=True)
        (out / "frame.json").write_text(json.dumps(frame, indent=2))
        (out / "audit.json").write_text(json.dumps(audit, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
