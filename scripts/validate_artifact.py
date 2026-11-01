#!/usr/bin/env python3
"""Validate the completeness and integrity of the archived 3,570-cell panel."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from verify_recovery_lineage import load_manifest, verify_recovery_lineage


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
INDEX = DATA / "combined_exploratory_3570_index.json"
RECOVERY_HASHES = DATA / "recovery_record_hashes.json"

EXPECTED_RHOS = {0.0, 0.25, 0.5, 0.75, 1.0}
EXPECTED_ORGANIZATIONS = {
    "single",
    "independent",
    "specialist_proactive",
    "informational_handoff",
    "committed_handoff",
    "mutual",
    "centralized_two_way",
}
EXPECTED_IDENTITY = {
    "design_version": "authority_communication_review_v20",
    "protocol_version": "communication_protocol_v21",
    "data_schema_version": "authority_communication_data_v9",
    "requested_model": "openai/gpt-6-luna",
    "provider_order": ["OpenAI"],
}
EXPECTED_ENDPOINT = "openai/gpt-6-luna-20260922"
EXPECTED_REQUEST = {
    "reasoning_effort": "low",
    "temperature": None,
    "max_output_tokens": 16000,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    source = json.loads(INDEX.read_text())
    rows = source["rows"]

    assert source["scheduled_cells"] == 3570
    assert len(rows) == 3570

    families = {row["family_id"] for row in rows}
    rhos = {float(row["rho"]) for row in rows}
    organizations = {row["organization"] for row in rows}
    keys = {
        (row["family_id"], float(row["rho"]), row["organization"])
        for row in rows
    }

    assert len(families) == 102
    assert rhos == EXPECTED_RHOS
    assert organizations == EXPECTED_ORGANIZATIONS
    assert len(keys) == 3570
    assert all(row["status"] == "complete" for row in rows)
    assert all(row["valid_submission"] is True for row in rows)

    expected_grid = {
        (family, rho, organization)
        for family in families
        for rho in EXPECTED_RHOS
        for organization in EXPECTED_ORGANIZATIONS
    }
    assert keys == expected_grid

    batches = Counter(row["batch"] for row in rows)
    assert batches == Counter({"original_60": 2100, "extension_42": 1470})

    recoveries = {row["original_failed_record_path"]: row for row in rows
                  if row.get("exceptional_recovery")}
    assert len(recoveries) == 4
    recovery_hashes = json.loads(RECOVERY_HASHES.read_text())["records"]
    assert {entry["path"] for entry in recovery_hashes} == set(recoveries)

    missing = [row["record_path"] for row in rows
               if not (DATA / row["record_path"]).is_file()]
    missing += [path for path in recoveries if not (DATA / path).is_file()]
    missing += [entry["path"] for entry in load_manifest(DATA)["records"]
                if not (DATA / entry["path"]).is_file()]
    if missing:
        print("Canonical index validation passed")
        print("Cells: 3,570")
        print("Families: 102")
        print("Rho values: 5")
        print("Organizations: 7")
        print(f"Raw record files missing: {len(missing)}")
        print("Download and extract the release asset listed in data/RAW_DATA_RELEASE.md")
        sys.exit(2)

    model_turns = 0
    for position, row in enumerate(rows, start=1):
        record_path = DATA / row["record_path"]
        assert sha256(record_path) == row["record_sha256"], (
            f"hash mismatch: {record_path}"
        )
        envelope = json.loads(record_path.read_text())
        assert envelope["run_id"] == row["run_id"]
        assert envelope["status"] == row["status"]
        assert envelope["attempts"][-1]["status"] == "complete"
        assert all(envelope.get(field) == value
                   for field, value in EXPECTED_IDENTITY.items())
        result = envelope["result"]
        for field in ("family_id", "rho", "organization", "valid_submission",
                      "exact_optimum", "decision_score", "raw_regret_m"):
            assert result[field] == row[field], (row["run_id"], field)
        for turn in result["turns"]:
            model = turn.get("model")
            if not isinstance(model, dict):
                continue
            model_turns += 1
            assert model["served_endpoint_model"] == EXPECTED_ENDPOINT
            assert model["provider"] == "OpenAI"
            request = model["request_parameters"]
            assert all(request.get(field) == value
                       for field, value in EXPECTED_REQUEST.items())
            assert request["provider"]["order"] == ["OpenAI"]
            assert request["provider"]["allow_fallbacks"] is False
        if position % 500 == 0:
            print(f"Verified {position} of {len(rows)} records")

    published_failures = {e["path"]: e for e in load_manifest(DATA)["records"]
                          if e["kind"] == "confirmed_failure"}
    assert set(published_failures) == set(recoveries)
    for entry in recovery_hashes:
        path = DATA / entry["path"]
        row = recoveries[entry["path"]]
        publication = published_failures[entry["path"]]
        assert publication["source_sha256"] == entry["sha256"] == row["original_failed_record_sha256"]
        assert sha256(path) == publication["sha256"], f"extract hash mismatch: {path}"
        prior = json.loads(path.read_text())
        assert prior["run_id"] == row["run_id"]
        assert prior["status"] == "confirmed_infrastructure_failure"
        assert all(prior.get(field) == value
                   for field, value in EXPECTED_IDENTITY.items())
        assert len(prior["attempts"]) == 2
        assert row["attempts"] == 3

    lineage = verify_recovery_lineage(DATA, rows)

    print("Artifact validation passed")
    print("Cells: 3,570")
    print("Families: 102")
    print("Rho values: 5")
    print("Organizations: 7")
    print("Record hashes: verified")
    print("Confirmed-failure extracts: 4 distributed hashes and original source-hash links verified")
    print("Recovery lineage: 8 original attempt envelopes and 13 technical extracts verified")
    print(f"Failed-attempt model responses: {lineage['failed_attempt_model_responses']} checked against resource totals")
    print(f"Model requests: {model_turns:,} checked for version and runtime settings")


if __name__ == "__main__":
    main()
