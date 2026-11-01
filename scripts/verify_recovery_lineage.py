"""Verify the three-attempt evidence chain for the four recovered cells."""
from __future__ import annotations

from datetime import datetime
from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_manifest(data: Path) -> dict:
    manifest = json.loads((data / "recovery_lineage.json").read_text())
    require(manifest["schema_version"] == "recovery_lineage_v2", "Unknown lineage schema")
    return manifest


def field_present(document: dict, path: str) -> bool:
    """Resolve dot-separated field paths used by technical-extract manifests."""
    value = document
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return False
        value = value[part]
    return True


def numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def equal_number(actual: float, expected: float, label: str) -> None:
    require(math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-9), label)


def verify_attempt_resources(payload: dict, label: str) -> int:
    """Recompute recorded request counts, known costs, and usage from traces."""
    resources = payload["resources"]
    models = [t["model"] for t in payload["turns"] if isinstance(t.get("model"), dict)]
    errors = payload["request_errors"]
    require(resources["recorded_model_responses"] == len(models), label + ": response count")
    require(resources["model_requests"] == len(models) + len(errors), label + ": request count")
    require(resources["request_retries"] == sum(e["will_retry"] for e in errors), label + ": retries")
    equal_number(resources["failed_request_time_s"], sum(e["elapsed_s"] for e in errors),
                 label + ": failed request time")
    unknown_usage = len(errors)
    unknown_cost = len(errors)
    for field in ("input_tokens", "output_tokens", "total_tokens"):
        values = [(m.get("usage") or {}).get(field) for m in models]
        equal_number(resources["known_" + field], sum(v for v in values if numeric(v)),
                     label + ": " + field)
    for model in models:
        usage = model.get("usage") or {}
        unknown_usage += not all(numeric(usage.get(k)) for k in
                                 ("input_tokens", "output_tokens", "total_tokens"))
        unknown_cost += not numeric(usage.get("cost"))
    costs = [(m.get("usage") or {}).get("cost") for m in models]
    equal_number(resources["known_cost_usd"], sum(v for v in costs if numeric(v)),
                 label + ": known cost")
    require(resources["requests_with_unknown_cost"] == unknown_cost, label + ": missing cost count")
    require(resources["requests_with_unknown_usage"] == unknown_usage, label + ": missing usage count")
    require(resources["cost_complete"] == (unknown_cost == 0), label + ": cost completeness")
    require(resources["usage_complete"] == (unknown_usage == 0), label + ": usage completeness")
    if unknown_cost:
        require(resources["cost_usd"] is None, label + ": unknown cost must not be zero")
    if unknown_usage:
        require(resources["total_tokens"] is None, label + ": unknown usage must not be zero")
    return len(models)


def verify_recovery_lineage(data: Path, index_rows: list[dict]) -> dict:
    manifest = load_manifest(data)
    recovered = {r["run_id"]: r for r in index_rows if r.get("exceptional_recovery")}
    require(len(recovered) == len(manifest["cells"]) == 4, "Expected exactly four recovered cells")
    require({c["run_id"] for c in manifest["cells"]} == set(recovered), "Recovery cell identity mismatch")
    entries = manifest["records"]
    require(len(entries) == 21, "Expected eight attempt files and thirteen technical extracts")
    require(len({e["path"] for e in entries}) == len(entries), "Duplicate lineage path")
    require(Counter(e["kind"] for e in entries) == {
        "attempt_envelope": 8, "inspection_resolution": 8,
        "exceptional_recovery_authorization": 1,
        "confirmed_failure": 4}, "Unexpected recovery record kinds")
    require(Counter(e["representation"] for e in entries) == {
        "original_bytes": 8, "technical_extract": 13}, "Unexpected recovery representations")
    documents = {}
    for entry in entries:
        path = PurePosixPath(entry["path"])
        require(not path.is_absolute() and ".." not in path.parts, "Invalid lineage path")
        raw = (data / entry["path"]).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == entry["sha256"], "Hash mismatch: " + str(path))
        document = json.loads(raw)
        if entry["representation"] == "technical_extract":
            publication = document["publication"]
            require(publication == {k: entry[k] for k in
                                    ("representation", "source_sha256", "omitted_fields")},
                    "Extract provenance mismatch: " + str(path))
            require(all(not field_present(document, k) for k in entry["omitted_fields"]),
                    "Omitted operational metadata present: " + str(path))
        else:
            require(entry["representation"] == "original_bytes", "Unknown representation")
        documents[entry["path"]] = document
    hashes = {e["path"]: e["sha256"] for e in entries}
    authorization = documents[manifest["authorization_record"]]
    require(set(authorization["original_records"]) == set(recovered), "Authorization scope mismatch")
    authorized_at = datetime.fromisoformat(authorization["approval_recorded_utc"]).timestamp()
    seen = {manifest["authorization_record"]}
    failed_responses = 0
    for cell in manifest["cells"]:
        run_id = cell["run_id"]
        row = recovered[run_id]
        require(all(cell[k] == row[k] for k in ("family_id", "rho", "organization")), run_id + ": cell identity")
        require(cell["confirmed_failure_record"] == row["original_failed_record_path"], run_id + ": failed path")
        require(cell["completed_record"] == row["record_path"], run_id + ": completed path")
        require(len(cell["attempt_records"]) == 3 and len(cell["resolution_records"]) == 2,
                run_id + ": incomplete chain")
        first_path, second_path, completed_path = cell["attempt_records"]
        require(completed_path == row["record_path"], run_id + ": third attempt path")
        first, second = documents[first_path], documents[second_path]
        completed_raw = (data / completed_path).read_bytes()
        prior = documents[cell["confirmed_failure_record"]]
        require(prior["publication"]["source_sha256"] == row["original_failed_record_sha256"],
                run_id + ": original confirmed-failure source hash")
        require(prior["publication"]["omitted_fields"] == [
            "inspection_resolution.reviewer", "inspection_resolution.note"],
            run_id + ": unexpected confirmed-failure omissions")
        require(hashlib.sha256(completed_raw).hexdigest() == row["record_sha256"], run_id + ": final hash")
        completed = json.loads(completed_raw)
        require(all(d["run_id"] == run_id for d in (first, second, prior, completed)), run_id + ": run ID")
        require(first["status"] == second["status"] == "inspection_required", run_id + ": inspection status")
        require(prior["status"] == "confirmed_infrastructure_failure" and completed["status"] == "complete",
                run_id + ": terminal status")
        require(len(first["attempts"]) == 1 and len(second["attempts"]) == 2 and len(completed["attempts"]) == 1,
                run_id + ": attempt history lengths")
        require(second["attempts"][:1] == first["attempts"], run_id + ": first attempt history changed")
        for key in ("attempts", "turns", "events", "resources", "request_errors", "schedule"):
            require(prior[key] == second[key], run_id + ": confirmed failure differs from second inspection: " + key)
        require(prior["rerun_of"]["archived_envelope_sha256"] == hashes[first_path], run_id + ": first hash link")
        require(prior["inspection_resolution"]["original_envelope_sha256"] == hashes[second_path],
                run_id + ": second hash link")
        batch = PurePosixPath(cell["confirmed_failure_record"]).parent
        require(str(batch / prior["rerun_of"]["archived_envelope"]) == first_path, run_id + ": first path link")
        require(str(batch / prior["inspection_resolution"]["original_envelope"]) == second_path,
                run_id + ": second path link")
        require(str(batch / prior["rerun_of"]["resolution"]) == cell["resolution_records"][0],
                run_id + ": resolution path link")
        for number, (history_path, resolution_path, history) in enumerate(zip(
                (first_path, second_path), cell["resolution_records"], (first, second)), 1):
            resolution = documents[resolution_path]
            require(resolution["run_id"] == run_id, run_id + ": resolution run ID")
            require(resolution["archived_envelope_sha256"] == hashes[history_path], run_id + ": resolution hash")
            require(str(batch / resolution["archived_envelope"]) == history_path, run_id + ": resolution path")
            require(resolution["decision"] == ("rerun_after_fix" if number == 1 else "confirm_failure"),
                    run_id + ": resolution decision")
            require(resolution["original_failure_type"] == history["failure_type"], run_id + ": failure type")
            require(resolution["prior_cell_started_events"] == number, run_id + ": prior attempt count")
            require(history["attempts"][-1]["resources"] == history["resources"], run_id + ": attempt resources")
            require(history["completed_unix_s"] <= resolution["resolved_unix_s"], run_id + ": resolution timing")
            failed_responses += verify_attempt_resources(history, run_id + f": attempt {number}")
        second_resolution = documents[cell["resolution_records"][1]]
        require(second_resolution["final_envelope_sha256"] == row["original_failed_record_sha256"],
                run_id + ": confirmed failure hash link")
        require(str(batch / second_resolution["final_envelope"]) == cell["confirmed_failure_record"],
                run_id + ": confirmed failure path link")
        auth = authorization["original_records"][run_id]
        require(auth == {"path": cell["confirmed_failure_record"],
                         "sha256": row["original_failed_record_sha256"], "prior_attempts": 2},
                run_id + ": authorization prior-record link")
        require(second_resolution["resolved_unix_s"] <= authorized_at <= completed["started_unix_s"],
                run_id + ": exceptional recovery timing")
        require(first["completed_unix_s"] <= second["started_unix_s"], run_id + ": attempt chronology")
        require(documents[cell["resolution_records"][0]]["resolved_unix_s"] <= second["started_unix_s"],
                run_id + ": retry authorization timing")
        verify_attempt_resources(completed["result"], run_id + ": completed recovery")
        require(completed["attempts"][0]["resources"] == completed["result"]["resources"],
                run_id + ": completed resource summary")
        attempts = [first["resources"], second["resources"], completed["result"]["resources"]]
        require(row["attempts"] == 3, run_id + ": combined attempt count")
        for field, actual in row["resources_all_attempts"].items():
            expected = all(a[field] for a in attempts) if isinstance(actual, bool) else sum(a[field] for a in attempts)
            if isinstance(actual, bool):
                require(actual == expected, run_id + ": combined " + field)
            else:
                equal_number(actual, expected, run_id + ": combined " + field)
        seen.update((first_path, second_path, cell["confirmed_failure_record"], *cell["resolution_records"]))
    require(seen == set(documents), "Unrelated or unreferenced files in recovery lineage")
    require(failed_responses == 44, "Expected 44 recorded responses across the failed attempts")
    return {"cells": 4, "attempt_envelopes": 8, "technical_extracts": 13,
            "failed_attempt_model_responses": failed_responses}


if __name__ == "__main__":
    data = ROOT / "data"
    rows = json.loads((data / "combined_exploratory_3570_index.json").read_text())["rows"]
    print(json.dumps(verify_recovery_lineage(data, rows), indent=2))
