"""Exact-optimal fixed-effect logit and reported probability contrasts."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from patsy import build_design_matrices
from scipy.special import expit
from scipy.stats import t
from statsmodels.stats.multitest import multipletests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "score"))
from run_score_poisson import BASE, DATA, ORGANIZATIONS, load_data, coefficients
from specifications import LOGIT


def inference(estimate, se, df):
    q = t.ppf(0.975, df)
    return dict(
        estimate=float(estimate), cluster_se=float(se),
        p_value=float(2 * t.sf(abs(estimate / se), df)) if se > 0 else 1.0,
        ci_low=float(estimate - q * se), ci_high=float(estimate + q * se),
    )


def contrast(result, vector, df):
    return inference(vector @ result.params,
                     np.sqrt(vector @ result.cov_params() @ vector), df)


def fit_logit(formula, data):
    return smf.glm(
        formula, data, family=sm.families.Binomial(),
    ).fit(
        maxiter=150, tol=1e-11, cov_type="cluster",
        cov_kwds={"groups": data.family_id, "use_correction": True},
    )


def run(specifications=LOGIT, output=HERE):
    output.mkdir(parents=True, exist_ok=True)
    full = load_data()
    index = json.loads((DATA / "combined_exploratory_3570_index.json").read_text())["rows"]
    binary = []
    for row in index:
        if row["rho"] not in (0, 1):
            continue
        result = json.loads((DATA / row["record_path"]).read_text())["result"]
        assert (row["exact_optimum"] == result["exact_optimum"]
                == (result["submitted_plan"] == result["optimal_plan"]))
        binary.append(dict(run_id=row["run_id"], optimal=int(result["exact_optimum"])))
    full = full.merge(pd.DataFrame(binary), on="run_id", validate="one_to_one")
    full.to_csv(output / "regression_data.csv", index=False)

    variation = full.groupby("family_id").optimal.nunique()
    excluded = variation[variation == 1].index.tolist()
    data = full[~full.family_id.isin(excluded)].copy()
    data.to_csv(output / "logit_regression_data.csv", index=False)
    family_audit = full.groupby("family_id").optimal.agg(["size", "sum", "nunique"]).reset_index()
    family_audit["included_in_logit"] = ~family_audit.family_id.isin(excluded)
    family_audit.to_csv(output / "logit_sample_audit.csv", index=False)

    df = data.family_id.nunique() - 1
    coef, effects, orgs, pairs, means, independent = ([], [], [], [], [], [])
    details, results = {}, {}
    for name, extra in specifications.items():
        formula = BASE.replace("score ~", "optimal ~") + extra
        result = fit_logit(formula, data)
        design_matrix = result.model.exog
        assert np.linalg.matrix_rank(design_matrix) == design_matrix.shape[1]
        assert np.isfinite(result.params).all() and np.isfinite(result.bse).all()
        assert result.converged
        results[name] = result
        coef.extend(dict(estimator="logit", **row)
                    for row in coefficients(result, name, df))
        detail = dict(
            formula=formula, n=int(result.nobs), parameters=len(result.params),
            clusters=int(df + 1), inference_df=int(df),
            converged=bool(result.converged),
            fitted_min=float(result.fittedvalues.min()),
            fitted_max=float(result.fittedvalues.max()),
            fitted_outside_01=int(((result.fittedvalues < 0)
                                   | (result.fittedvalues > 1)).sum()),
        )
        weights = (result.fittedvalues * (1 - result.fittedvalues)).to_numpy()
        detail.update(
            max_abs_coefficient=float(abs(result.params).max()),
            information_condition_number=float(np.linalg.cond(
                design_matrix.T @ (design_matrix * weights[:, None]))),
            score_max_abs=float(abs(design_matrix.T @
                                    (data.optimal - result.fittedvalues)).max()),
        )
        assert detail["fitted_outside_01"] == 0
        assert detail["max_abs_coefficient"] < 20
        assert detail["score_max_abs"] < 1e-6
        details[f"logit_{name}"] = detail

        def design(org, rho, averaged=False):
            authority, communication, commitment = ORGANIZATIONS[org]
            grid = (data.drop_duplicates("family_id").copy() if averaged
                    else data.iloc[:1].copy())
            grid = grid.assign(authority=authority, communication=communication,
                               commitment=commitment, rho=rho)
            return np.asarray(build_design_matrices(
                [result.model.data.design_info], grid)[0])

        def prediction(org, rho):
            matrix = design(org, rho, True)
            probabilities = expit(matrix @ result.params)
            gradient = (matrix * (probabilities * (1 - probabilities))[:, None]).mean(axis=0)
            return float(probabilities.mean()), gradient

        def comparison(first, second, rho):
            vector = design(first, rho)[0] - design(second, rho)[0]
            row = dict(estimator="logit", model=name, rho=rho, first=first,
                       second=second, **contrast(result, vector, df))
            first_probability, first_gradient = prediction(first, rho)
            second_probability, second_gradient = prediction(second, rho)
            gradient = first_gradient - second_gradient
            difference = inference(
                first_probability - second_probability,
                np.sqrt(gradient @ result.cov_params() @ gradient), df,
            )
            row.update(
                first_probability=first_probability,
                second_probability=second_probability,
                **{"probability_difference_" + key: value
                   for key, value in difference.items()},
            )
            return row

        for communication, (first, second) in enumerate([
            ("single", "independent"),
            ("specialist_proactive", "informational_handoff"),
            ("centralized_two_way", "mutual"),
        ]):
            vectors = [design(first, rho)[0] - design(second, rho)[0]
                       for rho in (0, 1)]
            for label, vector in zip(("rho0", "rho1", "change"),
                                     vectors + [vectors[1] - vectors[0]]):
                effects.append(dict(estimator="logit", model=name,
                                    communication=communication, contrast=label,
                                    **contrast(result, vector, df)))

        for rho in (0, 1):
            for org in ORGANIZATIONS:
                if org == "single" or (org == "committed_handoff"
                                       and "commitment" not in extra):
                    continue
                row = comparison(org, "single", rho)
                label = ("pooled_handoffs" if org == "informational_handoff"
                         and "commitment" not in extra else org)
                orgs.append(dict(estimator="logit", model=name, rho=rho,
                                 organization=label,
                                 **{key: value for key, value in row.items()
                                    if key not in ("estimator", "model", "rho",
                                                   "first", "second")}))

        for rho in (0, 1):
            for org in ORGANIZATIONS:
                if org in ("single", "independent") or (
                        org == "committed_handoff" and "commitment" not in extra):
                    continue
                row = comparison(org, "independent", rho)
                if org == "informational_handoff" and "commitment" not in extra:
                    row["first"] = "pooled_handoffs"
                independent.append(row)
        for org in ORGANIZATIONS:
            if org == "committed_handoff" and "commitment" not in extra:
                continue
            for rho in (0, 1):
                value, gradient = prediction(org, rho)
                label = ("pooled_handoffs" if org == "informational_handoff"
                         and "commitment" not in extra else org)
                means.append(dict(model=name, organization=label, rho=rho,
                                  probability=value,
                                  cluster_se=float(np.sqrt(
                                      gradient @ result.cov_params() @ gradient)),
                                  families=int(df + 1)))
        if "commitment" in extra:
            targets = [
                ("mutual", "single"),
                ("centralized_two_way", "single"),
                ("mutual", "independent"),
                ("centralized_two_way", "mutual"),
                ("committed_handoff", "informational_handoff"),
            ]
            for first, second in targets:
                for rho in (0, 1):
                    pairs.append(comparison(first, second, rho))
                vector = (design(first, 1) - design(second, 1)
                          - design(first, 0) + design(second, 0))[0]
                p11, g11 = prediction(first, 1)
                p01, g01 = prediction(second, 1)
                p10, g10 = prediction(first, 0)
                p00, g00 = prediction(second, 0)
                gradient = g11 - g01 - g10 + g00
                difference = inference(
                    p11 - p01 - p10 + p00,
                    np.sqrt(gradient @ result.cov_params() @ gradient), df,
                )
                pairs.append(dict(
                    estimator="logit", model=name, rho="change", first=first,
                    second=second, **contrast(result, vector, df),
                    **{"probability_difference_" + key: value
                       for key, value in difference.items()},
                ))

    independent = pd.DataFrame(independent)
    independent["probability_difference_p_holm_within_model_rho"] = independent.groupby(
        ["model", "rho"]).probability_difference_p_value.transform(
            lambda values: multipletests(values, method="holm")[1])
    independent["comparisons_in_group"] = independent.groupby(
        ["model", "rho"]).probability_difference_p_value.transform("size")
    independent.to_csv(output / "logit_contrasts_vs_independent.csv", index=False)
    orgs = pd.DataFrame(orgs)
    orgs["probability_difference_p_holm_within_model_rho"] = orgs.groupby(
        ["estimator", "model", "rho"]).probability_difference_p_value.transform(
            lambda values: multipletests(values, method="holm")[1])
    orgs["comparisons_in_group"] = orgs.groupby(
        ["estimator", "model", "rho"]).p_value.transform("size")
    orgs.to_csv(output / "contrasts_vs_single.csv", index=False)
    pd.DataFrame(coef).to_csv(output / "coefficients.csv", index=False)
    pd.DataFrame(effects).to_csv(output / "authority_effects.csv", index=False)
    pd.DataFrame(pairs).to_csv(output / "logit_selected_contrasts.csv", index=False)
    pd.DataFrame(means).to_csv(output / "logit_predicted_probabilities.csv", index=False)

    name = next(key for key, extra in specifications.items()
                if "commitment" in extra)
    alternative = fit_logit(
        "optimal ~ C(family_id)+C(organization)*rho", data)
    difference = float(max(abs(results[name].fittedvalues
                               - alternative.fittedvalues)))
    assert difference < 1e-8
    checks = dict(
        logit_org_parameterization_max_difference=difference,
        source_n=len(full), logit_n=len(data),
        logit_clusters=data.family_id.nunique(), excluded_families=excluded,
        excluded_runs=len(full) - len(data),
        reason="No within-family outcome variation; all 14 outcomes equal one in each excluded family.",
        logit_estimator="Unconditional binomial-logit MLE with family indicator coefficients, not conditional logit.",
        probability_standardization="Equal weight across retained families.",
        estimators=["logit"],
    )
    (output / "model_details.json").write_text(
        json.dumps(dict(models=details, validation=checks), indent=2) + "\n")
    print(f"Exact optimal: logit, {', '.join(specifications)}; "
          f"logit sample {len(data)}/{len(full)} runs")


if __name__ == "__main__":
    run()
