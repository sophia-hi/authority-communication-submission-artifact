# Additional 42 scenarios

The extension adds 42 economic scenarios to the original 60. Selection uses the economic generator and acceptance criteria; its inputs are scenario properties and candidate IDs. The original scenarios, policy labels, and Lead assignments remain fixed.

[`select_extension.py`](select_extension.py) scans subsequent candidate IDs in ascending order and takes the first seven accepted candidates in each of six strata. A stratum combines the substantive optimum at rho = 1 with the rho value where the optimum first changes. [`balance_extension.py`](balance_extension.py) assigns A/B labels and Lead sides to the additional scenarios, balancing the combined panel.

## Saved records

| File | Contents |
| --- | --- |
| [`extension_42_economic_families.json`](extension_42_economic_families.json) | Selected scenarios, selection rule, and candidate-scan audit |
| [`extension_42_assignment.json`](extension_42_assignment.json) | Label and Lead assignments for the extension |
| [`extension_42_assigned_families.json`](extension_42_assigned_families.json) | Additional scenarios with those assignments applied |
| [`combined_102_assigned_families.json`](combined_102_assigned_families.json) | Complete 102-scenario frame |
| [`combined_102_balance_audit.json`](combined_102_balance_audit.json) | Combined-panel balance checks |

The combined frame has 17 scenarios per stratum, a 51/51 Lead-side allocation, and a 51/51 premium-to-A mapping on each branch. The extension contributes 1,470 runs, bringing the full panel to 3,570.

## Verify selection and assignment

In the [analysis environment](../../docs/REPRODUCIBILITY.md#reproduce-reported-results), run from the repository root:

```bash
python data/extension_42/select_extension.py
python data/extension_42/balance_extension.py
```

By default, these commands regenerate the selection and assignment in memory and compare them with the saved records. Use `--out` for selection or `--out-dir` for balancing to save a separate regenerated copy.

The archived `source_sha256` values identify collection-time source files. Selection verification compares the scenario contents and selection metadata; separately saved regenerated copies record the current source hashes. The packaged configuration retains the parameters used by this panel, and its file hash differs from the collection-time configuration.
