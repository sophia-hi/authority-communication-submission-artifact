"""Reproduce the reported regressions, tables, and process audits offline."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "analysis/score/run_score_poisson.py",
    "analysis/optimal/run_optimal_logit.py",
    "analysis/optimal/validate_models.py",
    "analysis/build_tables.py",
    "mechanism-analysis/run_audits.py",
    "scripts/verify_reported_results.py",
)


def main() -> None:
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    for script in SCRIPTS:
        subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT,
                       env=env, check=True)


if __name__ == "__main__":
    main()
