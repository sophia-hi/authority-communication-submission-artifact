"""Score Poisson regressions, family-clustered inference, and organization contrasts."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from patsy import build_design_matrices
from scipy.stats import t
from statsmodels.stats.multitest import multipletests

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / "data"
sys.path.insert(0, str(HERE.parent))
from specifications import SCORE
ORGANIZATIONS = {  # authority, communication (0 none, 1 one-way, 2 two-way), commitment
    "independent": (0, 0, 0), "single": (1, 0, 0),
    "informational_handoff": (0, 1, 0), "committed_handoff": (0, 1, 1),
    "specialist_proactive": (1, 1, 0), "mutual": (0, 2, 0),
    "centralized_two_way": (1, 2, 0),
}
BASE = "score ~ C(family_id) + authority * C(communication) * rho"


def load_data():
    source = json.loads((DATA / "combined_exploratory_3570_index.json").read_text())
    rows = []
    for r in source["rows"]:
        if r["rho"] not in (0, 1):
            continue
        e = json.loads((DATA / r["record_path"]).read_text())
        last = e["attempts"][-1]
        assert r["status"] == last["status"] == "complete" and r["valid_submission"]
        assert e["run_id"] == r["run_id"]
        a, c, k = ORGANIZATIONS[r["organization"]]
        rows.append(dict(run_id=r["run_id"], family_id=r["family_id"],
                         organization=r["organization"], authority=a, communication=c,
                         commitment=k, rho=int(r["rho"]), score=r["decision_score"]))
    d = pd.DataFrame(rows).sort_values(["family_id", "rho", "organization"])
    assert len(d) == 1428 and d.run_id.is_unique
    assert d.groupby(["organization", "rho"]).size().eq(102).all()
    return d


def fit(formula, d):
    model = smf.glm(formula, data=d, family=sm.families.Poisson())
    assert np.linalg.matrix_rank(model.exog) == model.exog.shape[1], "Collinear model"
    result = model.fit(maxiter=100, tol=1e-10, cov_type="cluster",
                       cov_kwds={"groups": d.family_id, "use_correction": True})
    assert result.converged and np.isfinite(result.params).all()
    return result


def coefficients(result, model_id, df):
    rows = []
    for term in result.params.index:
        if term == "Intercept" or term.startswith("C(family_id)"):
            continue
        b, se = float(result.params[term]), float(result.bse[term])
        rows.append(dict(model=model_id, term=term, estimate=b, cluster_se=se,
                         p_value=2*t.sf(abs(b/se), df),
                         ci_low=b-t.ppf(.975, df)*se, ci_high=b+t.ppf(.975, df)*se))
    return rows


def margins(result, d, model_id, with_commitment):
    """Average over the same 102 family fixed effects."""
    rows = []
    for org, (a, c, k) in ORGANIZATIONS.items():
        if k and not with_commitment:
            continue
        for rho in (0, 1):
            grid = d.drop_duplicates("family_id").copy()
            grid = grid.assign(authority=a, communication=c, commitment=k, rho=rho)
            x = np.asarray(build_design_matrices([result.model.data.design_info], grid)[0])
            mu = np.exp(x @ result.params)
            value = mu.mean()
            gradient = (mu[:, None] * x).mean(axis=0)
            se = np.sqrt(gradient @ result.cov_params() @ gradient)
            q = t.ppf(.975, d.family_id.nunique()-1)
            rows.append(dict(model=model_id, organization=("pooled_handoffs" if c == 1 and a == 0 and not with_commitment else org), authority=a,
                             communication=c, commitment=k, rho=rho, predicted_score=value,
                             cluster_se=se, ci_low=value*np.exp(-q*se/value),
                             ci_high=value*np.exp(q*se/value)))
    return rows


def authority_effects(result, d, model_id):
    """A=1 versus A=0 log mean ratios at K=0, and their rho=1 minus rho=0 change."""
    rows = []
    q = t.ppf(.975, d.family_id.nunique()-1)
    for c in range(3):
        contrasts = []
        for rho in (0, 1):
            grid = pd.concat([d.iloc[:1]]*2, ignore_index=True).assign(
                authority=[0, 1], communication=c, rho=rho, commitment=0)
            x = np.asarray(build_design_matrices([result.model.data.design_info], grid)[0])
            contrasts.append(x[1]-x[0])
        for label, v in zip(("rho0", "rho1", "change"),
                            contrasts + [contrasts[1]-contrasts[0]]):
            b = float(v @ result.params)
            se = float(np.sqrt(v @ result.cov_params() @ v))
            rows.append(dict(model=model_id, communication=c, contrast=label,
                             estimate=b, cluster_se=se,
                             p_value=2*t.sf(abs(b/se), d.family_id.nunique()-1),
                             ci_low=b-q*se, ci_high=b+q*se,
                             ratio=np.exp(b), percent_change=100*np.expm1(b)))
    return rows


def organization_contrasts(result, d, model_id, with_commitment):
    df = d.family_id.nunique() - 1
    q = t.ppf(.975, df)

    def design(org, rho):
        a, c, k = ORGANIZATIONS[org]
        grid = d.iloc[:1].assign(authority=a, communication=c, commitment=k, rho=rho)
        return np.asarray(build_design_matrices([result.model.data.design_info], grid)[0])[0]

    def row(first, second, rho, vector):
        b = float(vector @ result.params)
        se = float(np.sqrt(vector @ result.cov_params() @ vector))
        return dict(model=model_id, first=first, second=second, rho=rho,
                    estimate=b, cluster_se=se, p_value=2*t.sf(abs(b/se), df),
                    ci_low=b-q*se, ci_high=b+q*se,
                    ratio=np.exp(b), percent_change=100*np.expm1(b))

    benchmarks = {}
    for second in ("single", "independent"):
        rows = []
        for rho in (0, 1):
            for first in ORGANIZATIONS:
                if first == second or (second == "independent" and first == "single"):
                    continue
                if first == "committed_handoff" and not with_commitment:
                    continue
                item = row(first, second, rho, design(first, rho)-design(second, rho))
                if first == "informational_handoff" and not with_commitment:
                    item["first"] = "pooled_handoffs"
                rows.append(item)
        frame = pd.DataFrame(rows)
        frame["p_holm_within_model_rho"] = frame.groupby("rho").p_value.transform(
            lambda p: multipletests(p, method="holm")[1])
        frame["comparisons_in_group"] = frame.groupby("rho").p_value.transform("size")
        benchmarks[second] = frame

    selected = []
    if with_commitment:
        targets = [("mutual", "single"), ("centralized_two_way", "single"),
                   ("mutual", "independent"), ("centralized_two_way", "mutual"),
                   ("committed_handoff", "informational_handoff")]
        for first, second in targets:
            vectors = [design(first, rho)-design(second, rho) for rho in (0, 1)]
            for rho, vector in zip((0, 1, "change"), vectors+[vectors[1]-vectors[0]]):
                selected.append(row(first, second, rho, vector))
    return benchmarks, selected


def run(specifications=SCORE, output=HERE):
    output.mkdir(parents=True, exist_ok=True)
    d = load_data()
    d.to_csv(output / "regression_data.csv", index=False)
    results, coef, cell_means, effects, metadata = {}, [], [], [], {}
    benchmarks = {"single": [], "independent": []}
    selected = []
    for model_id, extra in specifications.items():
        formula = BASE + extra
        result = fit(formula, d)
        results[model_id] = result
        coef += coefficients(result, model_id, d.family_id.nunique()-1)
        cell_means += margins(result, d, model_id, "commitment" in extra)
        effects += authority_effects(result, d, model_id)
        comparisons, pairs = organization_contrasts(result, d, model_id, "commitment" in extra)
        for benchmark in benchmarks:
            benchmarks[benchmark].append(comparisons[benchmark])
        selected += pairs
        metadata[model_id] = dict(formula=formula, nobs=int(result.nobs),
                                 parameters=len(result.params), converged=bool(result.converged),
                                 fitted_above_100=int((result.fittedvalues > 100).sum()))
    for name, rows in [("coefficients", coef), ("cell_predictions", cell_means),
                       ("authority_effects", effects), ("selected_contrasts", selected)]:
        pd.DataFrame(rows).to_csv(output / (name + ".csv"), index=False)
    for benchmark, frames in benchmarks.items():
        pd.concat(frames).to_csv(output / f"contrasts_vs_{benchmark}.csv", index=False)

    name = next(k for k, extra in specifications.items() if "commitment" in extra)
    alternative = fit("score ~ C(family_id) + C(organization) * rho", d)
    difference = float(np.max(abs(results[name].fittedvalues-alternative.fittedvalues)))
    assert difference < 1e-7
    checks = dict(equivalent_organization_model=name, equivalent_fitted_max_abs_diff=difference,
                  family_clusters=d.family_id.nunique(), p_value_df=d.family_id.nunique()-1)
    (output / "model_details.json").write_text(json.dumps(
        dict(models=metadata, checks=checks), indent=2) + "\n")
    print(f"Score Poisson: {', '.join(specifications)}, {len(d)} runs, {d.family_id.nunique()} families")


if __name__ == "__main__":
    run()
