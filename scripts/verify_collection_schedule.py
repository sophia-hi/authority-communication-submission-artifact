"""Check every archived schedule field against the three collection runners."""
from pathlib import Path
import json
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from schedule import build_schedule  # noqa: E402
from seed_design import build_frame  # noqa: E402
from timing_design import FIRST_BLOCK_SEED, build_timing_schedule  # noqa: E402


def main() -> None:
    cfg = yaml.safe_load((ROOT / "src/config.yaml").read_text())
    original, _ = build_frame(cfg)
    first = build_timing_schedule(original, FIRST_BLOCK_SEED)
    first_ids = {cell["run_id"] for cell in first}
    full = build_schedule(original, replicates=1, schedule_seed=20261013,
                          workers=4, replicate_waves=True)
    remaining = [cell for cell in full if cell["run_id"] not in first_ids]
    combined = json.loads((ROOT / "data/extension_42/combined_102_assigned_families.json").read_text())["families"]
    extension = [cell for cell in build_schedule(
        combined, replicates=1, schedule_seed=20261013, workers=64,
        replicate_waves=False) if cell["family_id"] >= 61]
    archived = json.loads((ROOT / "data/collection_schedule_3570.json").read_text())["rows"]
    expected = [
        *({**cell, "run_id": "stress420__" + cell["run_id"],
           "concurrency_lane": index % 64}
          for index, cell in enumerate(first)),
        *({**cell, "run_id": "explore2100__" + cell["run_id"],
           "scheduled_order": index + 1, "concurrency_lane": index % 64}
          for index, cell in enumerate(remaining)),
        *({**cell, "run_id": "extend3570__" + cell["run_id"],
           "scheduled_order": index + 1, "concurrency_lane": index % 64}
          for index, cell in enumerate(extension)),
    ]
    assert len(first) == 420 and len(remaining) == 1680 and len(extension) == 1470
    assert len(expected) == len(archived) == 3570
    expected_by_id = {cell["run_id"]: cell for cell in expected}
    archived_by_id = {row["run_id"]: row["schedule"] for row in archived}
    assert len(expected_by_id) == len(archived_by_id) == 3570
    assert expected_by_id == archived_by_id
    assert all(row["requested_model"] == "openai/gpt-6-luna"
               and row["provider_order"] == ["OpenAI"] for row in archived)
    print("Collection schedules verified: 420 + 1,680 + 1,470 cells; four documented recovery records")


if __name__ == "__main__":
    main()
