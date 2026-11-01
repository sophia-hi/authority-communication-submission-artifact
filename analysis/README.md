# Regression analyses

The exploratory main analyses use rho = 0 and 1. This folder contains model code, coefficient and comparison outputs, and the reported tables. Intermediate rho values are retained in the data archive.

With the raw records extracted and the [analysis environment](../docs/REPRODUCIBILITY.md#reproduce-reported-results) active, run from the repository root:

```bash
python scripts/reproduce_analysis.py
```

This rebuilds the regression tables and process analyses and checks the reported results.

## Models and samples

| Outcome | Models and entry point | Table | Sample |
| --- | --- | --- | --- |
| Normalized decision score | M1/M2: [`run_score_poisson.py`](score/run_score_poisson.py) | [Table 1](score/table_1_score.csv) | 1,428 runs, 102 scenarios |
| Exact company optimum | M3/M4: [`run_optimal_logit.py`](optimal/run_optimal_logit.py) | [Table A2](optimal/table_A2_optimal.csv) | 1,400 runs, 100 scenarios |

The model definitions are in [`specifications.py`](specifications.py). M1 and M3 include scenario fixed effects and the interaction of authority, categorical communication, and rho, with all lower-order terms. M2 and M4 add commitment and its interaction with rho. M1/M3 pool the two handoff arrangements; M2/M4 distinguish all seven arrangements. The scripts check the M2/M4 fit against equivalent organization-indicator specifications.

M1/M2 correspond to the “Organization structures” and “+ Commitment” columns in Table 1; M3/M4 are the corresponding columns in Table A2. Independent at rho = 0 is the reference. Scenarios are identified by `family_id`.

All four models use scenario-clustered CR1 covariance estimates. Tests and confidence intervals use t(101) for score and t(99) for logit. Coefficient stars denote unadjusted p-values: `***` p < .01, `**` p < .05, and `*` p < .10.

Logit includes explicit scenario indicators. Scenarios 73 and 85 have optimal outcomes in all 14 endpoint runs, giving no finite estimate for their logit intercepts; they are excluded from the logit sample. [`logit_sample_audit.csv`](optimal/logit_sample_audit.csv) records the inclusion decision for each scenario. Process analyses retain all 102 scenarios.

## Organizational comparisons

Reported score comparisons use M2; reported probability comparisons use M4. [Table A3](table_A3_selected_comparisons.csv) collects the selected comparisons.

| Measure | Definition |
| --- | --- |
| Score contrast | Log ratio of expected scores; `percent_change` is 100 × (exp(contrast) − 1) |
| Probability contrast | Predicted probability difference, averaged equally over the 100 retained scenarios |
| Change across rho endpoints | Change in the log score ratio or probability difference between rho = 0 and rho = 1 |

Probability standard errors use the delta method and the full coefficient covariance matrix. In logit output files, `estimate`, `cluster_se`, and `p_value` refer to log-odds contrasts. Columns beginning `probability_difference_` contain the probability contrasts and their tests. Probability differences use fractional units: .20 is 20 percentage points.

## Multiple comparisons

Holm adjustment is applied separately by outcome and rho endpoint to six comparisons against Single and five communicating arrangements against Independent. Score adjustments use coefficient-contrast p-values; probability adjustments use probability-difference p-values.

The adjusted columns are `p_holm_within_model_rho` for score and `probability_difference_p_holm_within_model_rho` for probability. The pooled M1/M3 specifications have five comparisons against Single and four against Independent. Other selected comparisons are unadjusted; a dash in Table A3 identifies a comparison without a reported adjustment.

## Output files and validation

The `score/` and `optimal/` folders contain coefficients, predictions, and organization comparisons. [`build_tables.py`](build_tables.py) formats Tables 1 and A2 and builds Table A3 from M2/M4 outputs. [`validate_models.py`](optimal/validate_models.py) independently checks the logit fit and the numerical probability gradient. [`verify_reported_results.py`](../scripts/verify_reported_results.py) checks selected estimates, p-values, sample sizes, and process counts.
