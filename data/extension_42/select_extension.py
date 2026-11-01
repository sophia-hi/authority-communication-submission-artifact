"""Select 42 untouched V18 economic families, seven per original stratum.

This script uses only the frozen economic generator and acceptance rule. It
does not inspect model outcomes and does not modify the original 60 families.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import yaml


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / "src"
sys.path.insert(0, str(SOURCE))

from generator import generate_candidate  # noqa: E402
from seed_design import acceptance_reasons  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path,
                        help="write a regenerated selection to a separate file")
    args = parser.parse_args()
    config = yaml.safe_load((SOURCE / "config.yaml").read_text())
    old_assignment = json.loads((SOURCE / "counterbalance_assignment.json").read_text())
    old_ids = {int(row["candidate_id"]) for row in old_assignment["assignments"]}
    assert len(old_ids) == 60
    start = max(old_ids) + 1
    strata = {
        (substantive, float(switch)): []
        for substantive in config["target_substantive_rho1"]
        for switch in config["target_transition_rho"]
    }
    assert len(strata) == 6
    rejected: Counter[str] = Counter()
    candidate_id = start
    while any(len(items) < 7 for items in strata.values()):
        family = generate_candidate(int(config["economic_master_seed"]), candidate_id)
        candidate_id += 1
        reasons = acceptance_reasons(family, config)
        if reasons:
            rejected.update(reasons)
            continue
        key = (family["substantive_optima"]["1.0"],
               float(family["first_grid_switch_rho"]))
        if key not in strata or len(strata[key]) >= 7:
            rejected["filled_or_unplanned_stratum"] += 1
            continue
        strata[key].append(family)
        print(f"accepted {sum(map(len, strata.values()))}/42: candidate {family['candidate_id']} {key}", flush=True)

    keys = sorted(strata, key=lambda key: (key[1], key[0]))
    selected = [strata[key][slot] for slot in range(7) for key in keys]
    assert len(selected) == 42
    assert not (old_ids & {family["candidate_id"] for family in selected})
    assert all(not acceptance_reasons(family, config) for family in selected)
    source_hashes = {
        filename: hashlib.sha256((SOURCE / filename).read_bytes()).hexdigest()
        for filename in ("generator.py", "seed_design.py", "config.yaml",
                         "counterbalance_assignment.json")
    }
    output = {
        "purpose": "exploratory_extension_to_existing_60_families",
        "economic_generator_version": config["economic_generator_version"],
        "economic_master_seed": config["economic_master_seed"],
        "candidate_start": start,
        "candidate_last_scanned": candidate_id - 1,
        "rule": "first seven accepted candidates in each of six pre-existing substantive-optimum x first-switch strata, scanning candidate IDs in ascending order",
        "source_sha256": source_hashes,
        "rejection_reason_counts": dict(sorted(rejected.items())),
        "families": selected,
    }
    if args.out:
        args.out.write_text(json.dumps(output, indent=2) + "\n")
        print(f"saved {args.out}; scanned {candidate_id - start} candidate IDs", flush=True)
    else:
        archived = json.loads((HERE / "extension_42_economic_families.json").read_text())
        # The collection-time hashes refer to the larger original config;
        # the reviewer source omits unused fields but selects the same families.
        if any(archived.get(key) != value for key, value in output.items()
               if key != "source_sha256"):
            raise ValueError("regenerated selection differs from archived families")
        print(f"Verified 42 archived families after scanning {candidate_id - start} candidates")


if __name__ == "__main__":
    main()
