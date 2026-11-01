"""Bounded, resumable execution of many experimental cells.

There are two separate concurrency controls:

* ``cell_workers`` limits how many experimental cells are active.
* ``request_concurrency`` limits all model requests, including requests that
  the organizational protocol launches concurrently inside one cell.

The second limit is essential: two active cells can each contain two agents
that act at the same time, so cell count alone is not a provider rate limit.
"""
from __future__ import annotations

import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
from time import monotonic, time
from typing import Any, Mapping, Sequence

from agent_interface import AgentInterfaceError
from data_schema import (DATA_SCHEMA_VERSION, DataRecordError,
                         envelope_record_errors,
                         validate_result_record, validate_version_identity)
from failure_policy import classify_failure
from live_cell import CellExecutor, LiveCellError, LiveCellInfrastructureError
from openrouter_client import (ModelTurn, OpenRouterResponsesClient,
                               TransientRequestRetriesExhausted)
from protocol import PROTOCOL_VERSION, ProtocolError


TERMINAL_STATUSES = {
    "complete", "organizational_terminal", "confirmed_infrastructure_failure",
}


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_json_once_or_match(path: Path, payload: Mapping[str, Any]) -> None:
    """Create immutable metadata, or confirm an existing exact copy."""
    existing = load_json(path)
    if existing is None:
        if path.exists():
            raise ValueError(f"existing file is not valid JSON: {path}")
        atomic_json(path, payload)
        return
    if existing != dict(payload):
        raise ValueError(f"refusing to overwrite existing file: {path}")


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _cell_started_count(progress_path: Path, run_id: str) -> int:
    if not progress_path.is_file():
        return 0
    count = 0
    for line in progress_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("event") == "cell_started" and row.get("run_id") == run_id:
            count += 1
    return count


def _rerun_authorization(
        output_dir: Path, progress_filename: str,
        run_id: str) -> dict[str, Any] | None:
    """Return one valid rerun authorization; at most two whole-cell attempts."""
    prior_starts = _cell_started_count(
        output_dir / progress_filename, run_id)
    if prior_starts == 0:
        return {}
    if prior_starts >= 2:
        return None
    resolutions = sorted(
        (output_dir / "inspection_resolutions").glob(
            f"{run_id}__resolution_*.json"))
    if not resolutions:
        return None
    resolution = load_json(resolutions[-1])
    if not resolution \
            or resolution.get("decision") != "rerun_after_fix" \
            or resolution.get("prior_cell_started_events") != prior_starts:
        return None
    archive_relative = resolution.get("archived_envelope")
    expected_hash = resolution.get("archived_envelope_sha256")
    if not isinstance(archive_relative, str) or not isinstance(expected_hash, str):
        return None
    archive = (output_dir / archive_relative).resolve()
    try:
        archive.relative_to(output_dir.resolve())
    except ValueError:
        return None
    if not archive.is_file():
        return None
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected_hash:
        return None
    resolution["_resolution_file"] = str(
        resolutions[-1].relative_to(output_dir))
    return resolution


def _authorized_inspection_rerun(
        output_dir: Path, progress_filename: str, run_id: str) -> bool:
    return _rerun_authorization(output_dir, progress_filename, run_id) is not None


class BoundedResponsesClient:
    """Share one hard request limit across all cells and their role agents."""

    def __init__(self, client: OpenRouterResponsesClient, limit: int):
        if limit < 1:
            raise ValueError("request concurrency must be positive")
        self.client = client
        self.settings = client.settings
        self.limit = limit
        self._semaphore = asyncio.Semaphore(limit)
        self._counter_lock = asyncio.Lock()
        self.active_requests = 0
        self.peak_active_requests = 0
        self.total_requests = 0

    async def create_response(
        self,
        *,
        input_items: str | Sequence[Mapping[str, Any]],
        instructions: str | None = None,
        tools: Sequence[Mapping[str, Any]] = (),
        metadata: Mapping[str, str] | None = None,
        previous_response_id: str | None = None,
        session_id: str | None = None,
    ) -> ModelTurn:
        async with self._semaphore:
            async with self._counter_lock:
                self.active_requests += 1
                self.total_requests += 1
                self.peak_active_requests = max(
                    self.peak_active_requests, self.active_requests)
            try:
                return await self.client.create_response(
                    input_items=input_items,
                    instructions=instructions,
                    tools=tools,
                    metadata=metadata,
                    previous_response_id=previous_response_id,
                    session_id=session_id,
                )
            finally:
                async with self._counter_lock:
                    self.active_requests -= 1


class ParallelPanelRunner:
    """Execute a fixed schedule with bounded concurrency and safe resume."""

    def __init__(
        self,
        *,
        frame: list[dict[str, Any]],
        schedule: list[dict[str, Any]],
        client: OpenRouterResponsesClient,
        output_dir: Path,
        dataset: str,
        design_master_seed: int,
        cell_workers: int,
        request_concurrency: int,
        transient_request_retries: int,
        emergency_max_model_requests: int,
        emergency_max_messages: int,
        consecutive_empty_round_limit: int = 3,
        expected_served_endpoint_model: str | None = None,
        expected_provider: str | None = None,
        retry_backoff_s: Sequence[float] = (2.0, 5.0),
        progress_filename: str = "progress.jsonl",
        summary_filename: str = "execution_summary.json",
    ):
        if cell_workers < 1:
            raise ValueError("cell_workers must be positive")
        if transient_request_retries < 0:
            raise ValueError("transient_request_retries cannot be negative")
        self.frame = {int(family["family_id"]): family for family in frame}
        self.schedule = schedule
        self.output_dir = output_dir
        self.dataset = dataset
        self.design_master_seed = design_master_seed
        self.cell_workers = cell_workers
        self.transient_request_retries = transient_request_retries
        self.emergency_max_model_requests = emergency_max_model_requests
        self.emergency_max_messages = emergency_max_messages
        self.consecutive_empty_round_limit = consecutive_empty_round_limit
        self.expected_served_endpoint_model = expected_served_endpoint_model
        self.expected_provider = expected_provider
        self.retry_backoff_s = tuple(float(x) for x in retry_backoff_s)
        self.progress_filename = progress_filename
        self.summary_filename = summary_filename
        self.client = BoundedResponsesClient(client, request_concurrency)
        self._progress_lock = asyncio.Lock()
        self._fatal_reason: str | None = None
        design_versions = {family.get("design_version") for family in frame}
        if (len(design_versions) != 1
                or not all(isinstance(value, str) and value
                           for value in design_versions)):
            raise ValueError("frame must contain one design_version")
        self.design_version = str(design_versions.pop())
        generator_versions = {
            family.get("economic_generator_version") for family in frame}
        if (len(generator_versions) != 1
                or not all(isinstance(value, str) and value
                           for value in generator_versions)):
            raise ValueError("frame must contain one economic_generator_version")
        self.economic_generator_version = str(generator_versions.pop())
        self.protocol_version = PROTOCOL_VERSION

    def _path(self, cell: Mapping[str, Any]) -> Path:
        return self.output_dir / f"{cell['run_id']}.json"

    async def _journal(self, payload: Mapping[str, Any]) -> None:
        record = {"unix_s": time(), **payload}
        async with self._progress_lock:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with (self.output_dir / self.progress_filename).open(
                    "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def _run_cell(self, cell: Mapping[str, Any]) -> str:
        output = self._path(cell)
        existing = load_json(output)
        if existing and existing.get("status") in TERMINAL_STATUSES:
            if existing.get("schedule") != dict(cell):
                raise ValueError(
                    "existing terminal envelope does not match the current "
                    f"schedule for run_id {cell['run_id']}")
            self._validate_terminal_envelope(existing, cell)
            await self._journal({
                "event": "cell_skipped_existing",
                "run_id": cell["run_id"],
                "status": existing["status"],
            })
            return "skipped_existing"
        if existing is not None:
            raise RuntimeError(
                "existing nonterminal cell requires inspection before resume: "
                f"{cell['run_id']} has status {existing.get('status')!r}")
        authorization = _rerun_authorization(
            self.output_dir, self.progress_filename, str(cell["run_id"]))
        if authorization is None:
            raise RuntimeError(
                "a prior cell record is missing without an authorized, archived "
                f"inspection resolution: {cell['run_id']}")

        family_id = int(cell["family_id"])
        if family_id not in self.frame:
            raise ValueError(f"unknown family_id {family_id}")
        family = self.frame[family_id]
        cell_started = time()
        prior_attempts: list[dict[str, Any]] = []
        rerun_of = None
        if authorization:
            archived = load_json(
                self.output_dir / str(authorization["archived_envelope"]))
            if archived:
                prior_attempts = list(archived.get("attempts", []))
            rerun_of = {
                "resolution": authorization.get("_resolution_file"),
                "archived_envelope": authorization["archived_envelope"],
                "archived_envelope_sha256": authorization[
                    "archived_envelope_sha256"],
            }
        envelope: dict[str, Any] = {
            "status": "running",
            "design_version": self.design_version,
            "economic_generator_version": self.economic_generator_version,
            "protocol_version": self.protocol_version,
            "data_schema_version": DATA_SCHEMA_VERSION,
            "started_unix_s": cell_started,
            "requested_model": self.client.settings.model,
            "provider_order": list(self.client.settings.provider_order),
            "dataset": self.dataset,
            "design_master_seed": self.design_master_seed,
            "run_id": cell["run_id"],
            "schedule": dict(cell),
            "attempts": prior_attempts,
            "rerun_of": rerun_of,
        }
        atomic_json(output, envelope)
        await self._journal({
            "event": "cell_started", "run_id": cell["run_id"]})
        executor = CellExecutor(
            self.client,
            emergency_max_model_requests=self.emergency_max_model_requests,
            emergency_max_messages=self.emergency_max_messages,
            expected_served_endpoint_model=self.expected_served_endpoint_model,
            expected_provider=self.expected_provider,
            capture_request_text=bool(cell.get("capture_request_text", False)),
            transient_request_retries=self.transient_request_retries,
            transient_retry_backoff_s=self.retry_backoff_s,
            consecutive_empty_round_limit=self.consecutive_empty_round_limit,
        )
        attempt_started = time()
        attempt_number = len(prior_attempts) + 1
        try:
            row = await executor.run(
                family, float(cell["rho"]), str(cell["organization"]),
                str(cell["run_id"]))
        except Exception as exc:
            disposition = classify_failure(exc)
            if disposition.treatment != "organizational_terminal":
                return await self._stop_for_inspection(
                    cell, envelope, executor, attempt_started,
                    exc, disposition.category, attempt_number)
            try:
                result = executor.organizational_failure_result(
                    family, float(cell["rho"]), str(cell["organization"]),
                    str(cell["run_id"]), exc)
                validate_result_record(result, "organizational_terminal")
            except Exception as validation_error:
                return await self._stop_for_inspection(
                    cell, envelope, executor, attempt_started,
                    validation_error,
                    ("result_schema_error"
                     if isinstance(validation_error, DataRecordError)
                     else "unexpected_exception"), attempt_number)
            envelope["attempts"].append({
                "attempt": attempt_number, "status": "organizational_terminal",
                "started_unix_s": attempt_started,
                "completed_unix_s": time(),
                "failure_type": type(exc).__name__,
                "failure_category": disposition.category,
                "failure_message": str(exc),
                "model_requests": executor.request_count,
                "resources": result["resources"],
            })
            envelope.update(
                status="organizational_terminal", completed_unix_s=time(),
                failure_type=type(exc).__name__,
                failure_category=disposition.category,
                failure_message=str(exc),
                turns=executor.turn_log, result=result)
            atomic_json(output, envelope)
            await self._journal({
                "event": "cell_completed", "run_id": cell["run_id"],
                "status": "organizational_terminal",
                "failure_type": type(exc).__name__})
            return "organizational_terminal"

        try:
            validate_result_record(row, "complete")
        except DataRecordError as exc:
            return await self._stop_for_inspection(
                cell, envelope, executor, attempt_started,
                exc, "result_schema_error", attempt_number)
        envelope["attempts"].append({
            "attempt": attempt_number, "status": "complete",
            "started_unix_s": attempt_started,
            "completed_unix_s": time(),
            "model_requests": executor.request_count,
            "resources": row["resources"],
        })
        envelope.update(status="complete", completed_unix_s=time(), result=row)
        atomic_json(output, envelope)
        await self._journal({
            "event": "cell_completed", "run_id": cell["run_id"],
            "status": "complete"})
        return "complete"

    async def _stop_for_inspection(
            self, cell: Mapping[str, Any], envelope: dict[str, Any],
            executor: CellExecutor, attempt_started: float,
            failure: BaseException, category: str,
            attempt_number: int) -> str:
        resources = executor.resource_summary()
        record = {
            "attempt": attempt_number,
            "status": "inspection_required",
            "started_unix_s": attempt_started,
            "completed_unix_s": time(),
            "failure_category": category,
            "failure_type": type(failure).__name__,
            "failure_message": str(failure),
            "model_requests": executor.request_count,
            "resources": resources,
        }
        envelope["attempts"].append(record)
        envelope.update(
            status="inspection_required", completed_unix_s=time(),
            failure_category=category,
            failure_type=type(failure).__name__,
            failure_message=str(failure),
            parallel_failures=getattr(failure, "parallel_failures", []),
            turns=executor.turn_log,
            events=[event.__dict__ for event in (
                executor.state.events if executor.state else [])],
            accepted_branch_actions=executor.accepted_branch_actions(),
            submission_audit=executor.submission_audit(),
            unapplied_calls=executor.unapplied_calls,
            calculator_calls=executor.calculator_log,
            request_errors=list(executor.client.error_log),
            resources=resources,
        )
        atomic_json(self._path(cell), envelope)
        self._fatal_reason = (
            f"inspection required for {cell['run_id']}: "
            f"{type(failure).__name__}: {failure}")
        await self._journal({
            "event": "cell_stopped_for_inspection",
            "run_id": cell["run_id"],
            "failure_category": category,
            "failure_type": type(failure).__name__,
            "failure_message": str(failure),
        })
        return "inspection_required"

    async def run(self) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        run_started_unix = time()
        run_started = monotonic()
        counts: Counter[str] = Counter()
        index = 0
        index_lock = asyncio.Lock()

        existing_nonterminal: list[dict[str, str]] = []
        for cell in self.schedule:
            envelope = load_json(self._path(cell))
            if envelope is None:
                if not _authorized_inspection_rerun(
                        self.output_dir, self.progress_filename,
                        str(cell["run_id"])):
                    existing_nonterminal.append({
                        "run_id": str(cell["run_id"]),
                        "status": "missing_after_prior_start_without_resolution",
                    })
                continue
            if envelope.get("status") in TERMINAL_STATUSES:
                if envelope.get("schedule") != dict(cell):
                    raise ValueError(
                        "existing terminal envelope does not match the current "
                        f"schedule for run_id {cell['run_id']}")
                self._validate_terminal_envelope(envelope, cell)
                continue
            existing_nonterminal.append({
                "run_id": str(cell["run_id"]),
                "status": str(envelope.get("status")),
            })
        if existing_nonterminal:
            self._fatal_reason = (
                "existing nonterminal cells require inspection before resume: "
                + json.dumps(existing_nonterminal, ensure_ascii=False))

        async def next_cell() -> Mapping[str, Any] | None:
            nonlocal index
            async with index_lock:
                if self._fatal_reason is not None or index >= len(self.schedule):
                    return None
                cell = self.schedule[index]
                index += 1
                return cell

        async def worker(worker_id: int) -> None:
            while True:
                cell = await next_cell()
                if cell is None:
                    return
                await self._journal({
                    "event": "cell_dispatched",
                    "worker": worker_id,
                    "run_id": cell["run_id"],
                    "scheduled_order": cell.get("scheduled_order"),
                })
                status = await self._run_cell(cell)
                counts[status] += 1

        workers = [asyncio.create_task(worker(i))
                   for i in range(self.cell_workers)]
        await asyncio.gather(*workers)
        terminal_validation = self._validate_terminal_envelopes()
        status = ("stopped_for_inspection" if self._fatal_reason else
                  "complete" if terminal_validation["valid"] else "incomplete")
        summary = {
            "status": status,
            "dataset": self.dataset,
            "started_unix_s": run_started_unix,
            "completed_unix_s": time(),
            "wall_time_s": monotonic() - run_started,
            "scheduled_cells": len(self.schedule),
            "dispatched_cells": sum(counts.values()),
            "undispatched_cells": len(self.schedule) - sum(counts.values()),
            "counts": dict(counts),
            "cell_workers": self.cell_workers,
            "request_concurrency": self.client.limit,
            "peak_active_requests": self.client.peak_active_requests,
            "total_model_requests": self.client.total_requests,
            "request_text_capture_cells": sum(
                bool(cell.get("capture_request_text", False))
                for cell in self.schedule),
            "fatal_reason": self._fatal_reason,
            "terminal_validation": terminal_validation,
        }
        atomic_json(self.output_dir / self.summary_filename, summary)
        await self._journal({"event": "panel_finished", **summary})
        return summary

    def _validate_terminal_envelopes(self) -> dict[str, Any]:
        """Verify every scheduled run has one matching terminal envelope."""
        missing: list[str] = []
        nonterminal: list[str] = []
        schedule_mismatches: list[str] = []
        for cell in self.schedule:
            run_id = str(cell["run_id"])
            envelope = load_json(self._path(cell))
            if envelope is None:
                missing.append(run_id)
                continue
            if envelope.get("status") not in TERMINAL_STATUSES:
                nonterminal.append(run_id)
                continue
            stored = envelope.get("schedule")
            if not isinstance(stored, dict) or stored != dict(cell):
                schedule_mismatches.append(run_id)
                continue
            try:
                self._validate_terminal_envelope(envelope, cell)
            except (ValueError, DataRecordError):
                schedule_mismatches.append(run_id)
        return {
            "valid": not (missing or nonterminal or schedule_mismatches),
            "expected_run_ids": len(self.schedule),
            "missing_run_ids": missing,
            "nonterminal_run_ids": nonterminal,
            "schedule_mismatch_run_ids": schedule_mismatches,
        }

    def _validate_terminal_envelope(
            self, envelope: Mapping[str, Any],
            cell: Mapping[str, Any]) -> None:
        expected = {
            "data_schema_version": DATA_SCHEMA_VERSION,
            "design_version": self.design_version,
            "economic_generator_version": self.economic_generator_version,
            "protocol_version": self.protocol_version,
            "dataset": self.dataset,
            "schedule": dict(cell),
        }
        validate_version_identity(envelope, expected, "terminal envelope")
        for field in ("dataset", "schedule"):
            if envelope.get(field) != expected[field]:
                raise ValueError(f"terminal envelope {field} mismatch")
        status = str(envelope.get("status"))
        if status in {"complete", "organizational_terminal"}:
            result = envelope.get("result")
            if not isinstance(result, Mapping):
                raise ValueError("terminal envelope lacks result")
            validate_result_record(result, status)
        elif status == "confirmed_infrastructure_failure":
            errors = envelope_record_errors(envelope)
            if errors:
                raise ValueError("; ".join(errors))
        else:
            raise ValueError(f"unsupported terminal status: {status}")
