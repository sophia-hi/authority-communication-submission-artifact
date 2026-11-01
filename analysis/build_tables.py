"""Format Tables 1, A2, and A3 from saved regression outputs."""
import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent
TERMS = [
    ("Authority", "authority"),
    ("One-way communication", "C(communication)[T.1]"),
    ("Two-way communication", "C(communication)[T.2]"),
    ("ρ", "rho"),
    ("Authority × One-way", "authority:C(communication)[T.1]"),
    ("Authority × Two-way", "authority:C(communication)[T.2]"),
    ("Authority × ρ", "authority:rho"),
    ("One-way × ρ", "C(communication)[T.1]:rho"),
    ("Two-way × ρ", "C(communication)[T.2]:rho"),
    ("Authority × One-way × ρ", "authority:C(communication)[T.1]:rho"),
    ("Authority × Two-way × ρ", "authority:C(communication)[T.2]:rho"),
    ("Commitment", "commitment"),
    ("Commitment × ρ", "commitment:rho"),
]


def build(folder, filename, n, clusters, models):
    with (HERE / folder / "coefficients.csv").open() as source:
        coef = {(r["model"], r["term"]): r for r in csv.DictReader(source)}
    rows = []
    for label, term in TERMS:
        cells = [label]
        for model in models:
            r = coef.get((model, term))
            if r is None:
                cells.append("—")
                continue
            p = float(r["p_value"])
            stars = "***" if p < .01 else "**" if p < .05 else "*" if p < .1 else ""
            estimate = float(r["estimate"])
            if abs(estimate) < 0.00005:
                estimate = 0.0
            cells.append(f"{estimate:.4f}{stars} ({float(r['cluster_se']):.4f})")
        rows.append(cells)
    rows += [["Observations", n, n], ["Scenario fixed effects", "Yes", "Yes"],
             ["Scenario clusters", clusters, clusters]]
    with (HERE / folder / filename).open("w", newline="") as target:
        writer = csv.writer(target, lineterminator="\n")
        writer.writerow(["Variable", *models])
        writer.writerows(rows)


def build_comparisons():
    def read(path):
        with (HERE / path).open() as source:
            return list(csv.DictReader(source))

    def select(rows, **criteria):
        matches = [row for row in rows
                   if all(row[key] == str(value) for key, value in criteria.items())]
        assert len(matches) == 1, criteria
        return matches[0]

    def p_text(value):
        return "< .001" if float(value) < .001 else f"{float(value):.3f}".lstrip("0")

    score = read("score/selected_contrasts.csv")
    probability = read("optimal/logit_selected_contrasts.csv")
    benchmarks = {name: read(f"score/contrasts_vs_{name}.csv")
                  for name in ("single", "independent")}
    probability_benchmark = read("optimal/contrasts_vs_single.csv")
    comparisons = [
        ("mutual", "single", 0, "Mutual vs Single"),
        ("mutual", "independent", 0, "Mutual vs Independent"),
        ("centralized_two_way", "mutual", "change", "Centralized Two-way vs Mutual"),
        ("committed_handoff", "informational_handoff", 0, "Committed vs Informational Handoff"),
        ("committed_handoff", "informational_handoff", 1, "Committed vs Informational Handoff"),
    ]
    rows = []
    for first, second, rho, label in comparisons:
        row = select(score, model="M2", first=first, second=second, rho=rho)
        change = rho == "change"
        estimate = (f"{float(row['estimate']):.4f}" if change
                    else f"{float(row['percent_change']):+.2f}%")
        holm = "—"
        if second in benchmarks:
            benchmark = select(benchmarks[second], model="M2", first=first,
                               second=second, rho=rho)
            holm = p_text(benchmark["p_holm_within_model_rho"])
        rows.append(["Expected score", "M2", label, "1 − 0" if change else rho,
                     estimate, p_text(row["p_value"]), holm,
                     "Change in log expected-score ratio" if change else "Relative expected-score difference"])

    for second, rho in [("single", 1), ("mutual", 1), ("mutual", "change")]:
        row = select(probability, model="M4", first="centralized_two_way",
                     second=second, rho=rho)
        holm = "—"
        if second == "single":
            benchmark = select(probability_benchmark, model="M4",
                               organization="centralized_two_way", rho=rho)
            holm = p_text(benchmark["probability_difference_p_holm_within_model_rho"])
        change = rho == "change"
        rows.append(["Optimal-decision probability", "M4",
                     f"Centralized Two-way vs {second.title()}", "1 − 0" if change else rho,
                     f"{100 * float(row['probability_difference_estimate']):+.0f} pp",
                     p_text(row["probability_difference_p_value"]), holm,
                     "Change in probability difference" if change else "Probability difference"])
    with (HERE / "table_A3_selected_comparisons.csv").open("w", newline="") as target:
        writer = csv.writer(target, lineterminator="\n")
        writer.writerow(["Outcome", "Model", "Comparison", "ρ", "Estimate", "p", "Holm p", "Scale"])
        writer.writerows(rows)


if __name__ == "__main__":
    build("score", "table_1_score.csv", 1428, 102, ("M1", "M2"))
    build("optimal", "table_A2_optimal.csv", 1400, 100, ("M3", "M4"))
    build_comparisons()
