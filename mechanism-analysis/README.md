# Process analyses

These four analyses describe how recorded calculations, messages, and decisions relate to final outcomes. They retain the run references needed to inspect individual cases.

After extracting the raw records and activating the [analysis environment](../docs/REPRODUCIBILITY.md#reproduce-reported-results), run from the repository root:

```bash
python mechanism-analysis/run_audits.py
```

The command runs the scripts in dependency order and rebuilds their CSV outputs. The [full reproduction command](../docs/REPRODUCIBILITY.md#reproduce-reported-results) also runs these analyses.

| Comparison | Folder | Evidence |
| --- | --- | --- |
| Single–Mutual at rho = 0; Single–Centralized Two-way at rho = 1 | [`single_benchmark/`](single_benchmark/) | Local-profit calculations, company rankings, submitted choices, requests, and replies |
| Independent–Mutual at rho = 0 | [`independent_communication/`](independent_communication/) | Branch calculations, policy rankings, labels, and messages |
| Centralized Two-way–Mutual | [`centralized_mutual/`](centralized_mutual/) | Joint outcomes, reconstructed rankings, message timing, and submission rounds |
| Committed–Informational Handoff | [`commitment/`](commitment/) | Sender commitments, receiver responses, and feasible company plans |

## Trace an output to its source

Each analysis retains all 102 scenarios for its selected arrangements and endpoints, including successful, unsuccessful, and unclassified runs. The handoff summary also includes intermediate rho values.

`runs.csv` gives the raw `record_path`. Expression and message tables join to runs by scenario (`family`), organization, and rho where applicable. Calculator call/item IDs and message delivery IDs locate the evidence within the JSON record.

## Calculation and message coding

Local-profit analyses identify expressions using policy-specific fixed costs and match numeric values at a tolerance of .001 million. `sensitivity.csv` repeats the matching at .0001 and .01 million. `manual_review.csv` records reviewed calculation errors; `EXCLUDE`, `LABEL_INVERSION`, and `REVIEWED_MATCHES` in the relevant scripts identify reviewed exceptions.

For Single at rho = 1, [`rho1_audit/`](single_benchmark/rho1_audit/) examines calculation inputs and [`rho1_process/`](single_benchmark/rho1_process/) reconstructs company rankings. A complete comparison requires identifiable values for all four policy pairs before submission. Ranking and ranking–submission mismatch counts use this reconstructable subset. Unmapped expressions remain in `expression_trace.csv`, and unclassified runs remain in the output tables. Reviewed request coding is stored in `rho1_audit/audit.py`; recommendation and reminder coding is in `rho1_process/summarize.py`. The generated CSVs retain the message text.

For Independent–Mutual, `branch_process.csv` distinguishes an incorrect calculated ranking from a submitted action inconsistent with the calculated ranking. `wrong_after_correct_values` additionally requires correct local-profit values. `message_process.csv` contains the corresponding label and ordering evidence.

## Submission timing

The Centralized Two-way–Mutual analysis measures submission order by protocol round. The executor collects both agents' protocol actions before applying that round's decisions; same-round submissions are therefore concurrent.

For Mutual submissions in different rounds, `process_indicators.csv` contains:

| Fields | Meaning |
| --- | --- |
| `first_branch`, `first_filing_round`, `second_filing_round` | Earlier-submitting branch and the two submission rounds |
| `first_filing_excludes_optimum` | Whether the earlier submitted policy makes the company optimum unattainable |
| `other_correct_comparison_before_first_filing` | The later-submitting agent has a reconstructable correct comparison in an earlier round |
| `other_correct_comparison_same_round_as_first_filing` | Such a comparison occurs in the first submission's round |
| `other_correct_comparison_after_first_filing` | Such a comparison occurs in a later round |

These order-dependent fields, together with `first_filing_at`, are blank for concurrent Mutual submissions and Centralized Two-way runs. Blank means not applicable; `False` means an applicable indicator was not observed. `same_round_filing` and the round values in `turns.csv` identify concurrent cases.

`comparison_expressions.csv` links calculations to their rounds. The three comparison indicators can overlap when correct comparisons occur in multiple rounds. A same-round comparison is classified as concurrent with the first submission and does not establish a response to it. Completion timestamps (`time`, `first_filing_at`, and `filing_gap`) describe elapsed timing; protocol rounds determine cross-agent order. `message_timing.csv` distinguishes sending from reading, with read times identifying information available before submission.

At rho = 1, Mutual has 33 failures: 27 with submissions in different rounds and six with concurrent submissions. In 19 of the 27 different-round failures, the earlier policy excludes the company optimum. [`submission_timing_summary.csv`](centralized_mutual/submission_timing_summary.csv) gives these counts and the 102-run denominator. `all_failure_census.csv` includes all failures, including the six concurrent cases.

## Handoff outcomes

The handoff measures decompose the final outcome:

| Field | Meaning |
| --- | --- |
| `lead_conditional_optimal` | The receiver chooses the best response to the sender's actual final action |
| `report_restriction_regret` | Profit lost by restricting feasible plans to the sender's final action |
| `lead_response_regret` | Additional loss from the receiver's response |

Message read times identify the information available before the receiver submits. These measures are descriptive outcome decompositions.

## Reported counts and checks

The outputs include calculation errors, unmapped expressions, unsuccessful revisions, and multiplicity-adjusted process tests. At rho = 1, complete company comparisons are reconstructable in 58 Single runs and 61 Centralized Two-way runs; correct rankings occur in 51 and 48 runs, respectively.

[`verify_reported_results.py`](../scripts/verify_reported_results.py) checks the principal process counts and regression contrasts. Run references and evidence IDs connect the reported counts to the archived records.
