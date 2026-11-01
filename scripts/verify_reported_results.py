"""Check saved outputs against the reported contrasts and process counts."""
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return pd.read_csv(ROOT / name)


def contrast(frame, first, second, rho, model="M2"):
    rows = frame[(frame.model == model) & (frame["first"] == first)
                 & (frame["second"] == second) & (frame.rho.astype(str) == str(rho))]
    assert len(rows) == 1
    return rows.iloc[0]


def close(actual, expected, tolerance=1e-7):
    assert np.isclose(actual, expected, rtol=0, atol=tolerance), (actual, expected)


def reported(actual, expected, decimals):
    assert round(float(actual), decimals) == expected, (actual, expected)


def verify_holm(frame, raw_column, adjusted_column):
    for _, group in frame.groupby(["model", "rho"]):
        expected = multipletests(group[raw_column], method="holm")[1]
        assert np.allclose(group[adjusted_column], expected, rtol=0, atol=1e-12)


def main():
    score = read("analysis/score/selected_contrasts.csv")
    logit = read("analysis/optimal/logit_selected_contrasts.csv")
    score_coefs = read("analysis/score/coefficients.csv")
    for term, estimate, p_value in [
        ("C(communication)[T.2]", .0661, .006),
        ("authority:rho", .2041, None),
        ("C(communication)[T.2]:rho", .1512, .005),
        ("commitment", .0587, .018),
        ("commitment:rho", .0783, .049),
    ]:
        rows = score_coefs[(score_coefs.model == "M2")
                           & (score_coefs.term == term)]
        assert len(rows) == 1
        reported(rows.iloc[0].estimate, estimate, 4)
        if p_value is None:
            assert rows.iloc[0].p_value < .001
        else:
            reported(rows.iloc[0].p_value, p_value, 3)

    row = contrast(score, "mutual", "single", 0)
    close(row.percent_change, 4.6664788003)
    close(row.p_value, .03634995427525)
    single_score = read("analysis/score/contrasts_vs_single.csv")
    assert single_score[single_score.model == "M2"].groupby("rho").size().to_dict() == {0: 6, 1: 6}
    rows = single_score[(single_score.model == "M2")
                        & (single_score["first"] == "mutual")
                        & (single_score["second"] == "single")
                        & (single_score.rho == 0)]
    assert len(rows) == 1
    reported(rows.iloc[0].p_holm_within_model_rho, .218, 3)

    row = contrast(score, "centralized_two_way", "mutual", "change")
    close(row.estimate, .079170509988304)
    close(row.p_value, .035177675793)
    reported(row.estimate, .0792, 4)
    row = contrast(logit, "centralized_two_way", "single", 1, "M4")
    close(row.probability_difference_estimate, .20)
    reported(row.probability_difference_p_value, .002, 3)
    single_logit = read("analysis/optimal/contrasts_vs_single.csv")
    assert single_logit[single_logit.model == "M4"].groupby("rho").size().to_dict() == {0: 6, 1: 6}
    rows = single_logit[(single_logit.model == "M4")
                        & (single_logit.organization == "centralized_two_way")
                        & (single_logit.rho == 1)]
    assert len(rows) == 1
    reported(rows.iloc[0].probability_difference_p_holm_within_model_rho, .007, 3)

    independent_score = read("analysis/score/contrasts_vs_independent.csv")
    assert independent_score[independent_score.model == "M2"].groupby("rho").size().to_dict() == {0: 5, 1: 5}
    rows = independent_score[(independent_score.model == "M2")
                             & (independent_score["first"] == "mutual")
                             & (independent_score.rho == 0)]
    assert len(rows) == 1
    reported(rows.iloc[0].percent_change, 6.83, 2)
    reported(rows.iloc[0].p_value, .006, 3)
    reported(rows.iloc[0].p_holm_within_model_rho, .028, 3)
    independent_logit = read("analysis/optimal/logit_contrasts_vs_independent.csv")
    assert independent_logit[independent_logit.model == "M4"].groupby("rho").size().to_dict() == {0: 5, 1: 5}
    rows = independent_logit[(independent_logit.model == "M4")
                             & (independent_logit["first"] == "mutual")
                             & (independent_logit.rho == 0)]
    assert len(rows) == 1
    reported(rows.iloc[0].probability_difference_estimate, .13, 2)
    reported(rows.iloc[0].probability_difference_p_value, .003, 3)
    reported(rows.iloc[0].probability_difference_p_holm_within_model_rho, .017, 3)

    for frame in (single_score, independent_score):
        verify_holm(frame, "p_value", "p_holm_within_model_rho")
    for frame in (single_logit, independent_logit):
        verify_holm(frame, "probability_difference_p_value",
                    "probability_difference_p_holm_within_model_rho")

    row = contrast(logit, "centralized_two_way", "mutual", 1, "M4")
    close(row.probability_difference_estimate, .15)
    reported(row.probability_difference_p_value, .017, 3)
    row = contrast(logit, "centralized_two_way", "mutual", "change", "M4")
    close(row.probability_difference_estimate, .17)
    close(row.probability_difference_p_value, .01481480745684)
    reported(row.estimate, 1.3326, 4)
    reported(row.p_value, .100, 3)
    for rho, expected in [(0, 6.0471564), (1, 14.68287967)]:
        close(contrast(score, "committed_handoff", "informational_handoff", rho).percent_change,
              expected, 1e-6)
    for rho, score_percent, logit_difference, probability_p in [
        (0, 6.05, .11, .020),
        (1, 14.68, .16, .001),
    ]:
        reported(contrast(score, "committed_handoff", "informational_handoff", rho).percent_change,
                 score_percent, 2)
        row = contrast(logit, "committed_handoff", "informational_handoff", rho, "M4")
        reported(row.probability_difference_estimate, logit_difference, 2)
        reported(row.probability_difference_p_value, probability_p, 3)
    audit = read("analysis/optimal/logit_sample_audit.csv")
    assert set(audit.loc[~audit.included_in_logit, "family_id"]) == {73, 85}
    assert audit.loc[~audit.included_in_logit, "size"].eq(14).all()
    assert audit.loc[~audit.included_in_logit, "sum"].eq(14).all()
    assert len(read("analysis/score/regression_data.csv")) == 1428
    assert len(read("analysis/optimal/logit_regression_data.csv")) == 1400
    assert set(read("analysis/optimal/coefficients.csv").model) == {"M3", "M4"}
    assert set(score_coefs.model) == {"M1", "M2"}
    a3 = pd.read_csv(ROOT / "analysis/table_A3_selected_comparisons.csv", dtype=str)
    assert a3[["Estimate", "p", "Holm p"]].values.tolist() == [
        ["+4.67%", ".036", ".218"],
        ["+6.83%", ".006", ".028"],
        ["0.0792", ".035", "—"],
        ["+6.05%", ".018", "—"],
        ["+14.68%", "< .001", "—"],
        ["+20 pp", ".002", ".007"],
        ["+15 pp", ".017", "—"],
        ["+17 pp", ".015", "—"],
    ]

    base = "mechanism-analysis/"
    rho0 = read(base + "single_benchmark/rho0_audit/runs.csv")
    assert rho0.groupby("org").wrong_after_correct_values.sum().to_dict() == {"single": 7, "mutual": 1}
    rho1 = read(base + "single_benchmark/rho1_process/runs_coded.csv")
    for metric, expected in [
        ("complete_comparison", {"single": 58, "centralized_two_way": 61}),
        ("ranking_correct", {"single": 51, "centralized_two_way": 48}),
        ("identified_ranking_action_break", {"single": 13, "centralized_two_way": 4}),
    ]:
        assert rho1.groupby("org")[metric].sum().to_dict() == expected
    independent = read(base + "independent_communication/runs_process.csv")
    assert independent.groupby("org").ranking_action_break.sum().to_dict() == {"independent": 13, "mutual": 1}
    assert independent.groupby("org").wrong_after_correct_values.sum().to_dict() == {"independent": 11, "mutual": 1}
    coordination = read(base + "centralized_mutual/process_indicators.csv")
    mutual = coordination[coordination.org == "mutual"]
    assert len(mutual) == mutual.family.nunique() == 102
    failures = mutual[~mutual.exact]
    different = failures[failures.same_round_filing.eq(False)]
    concurrent = mutual[mutual.same_round_filing.eq(True)]
    assert len(failures) == 33
    assert len(different) == 27
    assert (~concurrent.exact).sum() == 6
    assert different.first_filing_excludes_optimum.eq(True).sum() == 19
    order_fields = [
        "first_branch", "first_filing_round", "second_filing_round",
        "first_filing_at", "first_filing_excludes_optimum",
        "other_correct_comparison_before_first_filing",
        "other_correct_comparison_same_round_as_first_filing",
        "other_correct_comparison_after_first_filing",
    ]
    assert concurrent[order_fields].isna().all().all()
    assert coordination[coordination.org == "centralized_two_way"][order_fields].isna().all().all()
    ordered = mutual[mutual.same_round_filing.eq(False)]
    assert len(ordered) == 72 and len(concurrent) == 30
    assert ordered[order_fields].notna().all().all()
    assert (ordered.first_filing_round < ordered.second_filing_round).all()
    summary = read(base + "centralized_mutual/submission_timing_summary.csv")
    assert summary.to_dict("records") == [{
        "org": "mutual", "rho": 1, "runs": 102, "failures": 33,
        "different_round_runs": 72, "same_round_runs": 30,
        "different_round_failures": 27, "same_round_failures": 6,
        "earlier_submission_excludes_optimum_failures": 19,
    }]
    handoffs = read(base + "commitment/runs.csv")
    assert handoffs[handoffs.rho == 1].groupby("org").lead_conditional_optimal.sum().to_dict() == {
        "committed_handoff": 95, "informational_handoff": 61}
    print("Reported regression contrasts and process counts: passed")


if __name__ == "__main__":
    main()
