"""Rebuild the process evidence from archived records and reviewed coding."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = [
    "single_benchmark/rho0_audit/audit.py",
    "single_benchmark/rho1_audit/audit.py",
    "single_benchmark/rho1_process/analyze.py",
    "single_benchmark/rho1_process/summarize.py",
    "independent_communication/audit.py",
    "independent_communication/process.py",
    "centralized_mutual/audit.py",
    "centralized_mutual/comparisons.py",
    "centralized_mutual/process.py",
    "commitment/analyze.py",
    "commitment/comparisons.py",
    "commitment/comparison_diagnostics.py",
]

if __name__ == "__main__":
    for name in SCRIPTS:
        print(name, flush=True)
        result = subprocess.run([sys.executable, str(HERE / name)], capture_output=True, text=True)
        if result.returncode:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            raise SystemExit(result.returncode)
    print("Process audits completed")
