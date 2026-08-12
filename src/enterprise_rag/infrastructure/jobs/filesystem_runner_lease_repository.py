from __future__ import annotations

import asyncio
import fcntl
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from enterprise_rag.application.dto.runner import RunnerLeaseDto, RunnerLifecycle
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.workspace.file_io import atomic_write_json
from enterprise_rag.infrastructure.workspace.path_security import is_link_or_reparse, is_within


class FilesystemRunnerLeaseRepository:
    def __init__(self, var_root: Path) -> None:
        if is_link_or_reparse(var_root):
            raise revision_error("LINK_NOT_ALLOWED")
        try:
            var_root.mkdir(parents=True, exist_ok=True)
            resolved_var_root = var_root.expanduser().resolve(strict=True)
            self._jobs_root = resolved_var_root / "jobs"
            self._jobs_root.mkdir(exist_ok=True)
        except OSError as error:
            raise revision_error("IO_FAILURE") from error

    async def begin_launch(
        self,
        job_id: str,
        runner_token: str,
        occurred_at: datetime,
    ) -> RunnerLeaseDto:
        return await asyncio.to_thread(
            self._update,
            job_id,
            lambda current: RunnerLeaseDto(
                job_id=job_id,
                runner_token=runner_token,
                launch_sequence=1 if current is None else current.launch_sequence + 1,
                process_id=None,
                lifecycle=RunnerLifecycle.LAUNCHING,
                started_at=occurred_at,
                heartbeat_at=occurred_at,
            ),
        )

    async def claim(
        self,
        job_id: str,
        runner_token: str,
        process_id: int,
        occurred_at: datetime,
    ) -> RunnerLeaseDto:
        def mutate(current: RunnerLeaseDto | None) -> RunnerLeaseDto:
            owned = self._require_owner(current, runner_token)
            if owned.lifecycle is RunnerLifecycle.RUNNING:
                if owned.process_id != process_id:
                    raise revision_error("RUNNER_LEASE_CONFLICT", {"job_id": job_id})
                return owned
            if owned.lifecycle is not RunnerLifecycle.LAUNCHING:
                raise revision_error("RUNNER_LEASE_CONFLICT", {"job_id": job_id})
            self._require_monotonic(owned, occurred_at, job_id)
            return replace(
                owned,
                process_id=process_id,
                lifecycle=RunnerLifecycle.RUNNING,
                heartbeat_at=occurred_at,
            )

        return await asyncio.to_thread(self._update, job_id, mutate)

    async def heartbeat(
        self,
        job_id: str,
        runner_token: str,
        process_id: int,
        occurred_at: datetime,
    ) -> RunnerLeaseDto:
        def mutate(current: RunnerLeaseDto | None) -> RunnerLeaseDto:
            owned = self._require_owner(current, runner_token)
            if (
                owned.lifecycle is not RunnerLifecycle.RUNNING
                or owned.process_id != process_id
            ):
                raise revision_error("RUNNER_LEASE_CONFLICT", {"job_id": job_id})
            self._require_monotonic(owned, occurred_at, job_id)
            return replace(owned, heartbeat_at=occurred_at)

        return await asyncio.to_thread(self._update, job_id, mutate)

    async def finish(
        self,
        job_id: str,
        runner_token: str,
        process_id: int | None,
        lifecycle: RunnerLifecycle,
        occurred_at: datetime,
        error_code: str | None = None,
    ) -> RunnerLeaseDto:
        if lifecycle not in {RunnerLifecycle.EXITED, RunnerLifecycle.FAILED}:
            raise revision_error("RUNNER_LEASE_CONFLICT", {"job_id": job_id})

        def mutate(current: RunnerLeaseDto | None) -> RunnerLeaseDto:
            owned = self._require_owner(current, runner_token)
            if owned.lifecycle in {RunnerLifecycle.EXITED, RunnerLifecycle.FAILED}:
                if (
                    owned.lifecycle is lifecycle
                    and owned.process_id == process_id
                    and owned.error_code == error_code
                ):
                    return owned
                raise revision_error("RUNNER_LEASE_CONFLICT", {"job_id": job_id})
            if owned.process_id != process_id:
                raise revision_error("RUNNER_LEASE_CONFLICT", {"job_id": job_id})
            self._require_monotonic(owned, occurred_at, job_id)
            try:
                return replace(
                    owned,
                    lifecycle=lifecycle,
                    heartbeat_at=occurred_at,
                    finished_at=occurred_at,
                    error_code=error_code,
                )
            except ValueError as error:
                raise revision_error(
                    "RUNNER_LEASE_CONFLICT", {"job_id": job_id}
                ) from error

        return await asyncio.to_thread(self._update, job_id, mutate)

    async def load(self, job_id: str) -> RunnerLeaseDto | None:
        return await asyncio.to_thread(self._load_locked, job_id)

    def _update(
        self,
        job_id: str,
        mutate: Callable[[RunnerLeaseDto | None], RunnerLeaseDto],
    ) -> RunnerLeaseDto:
        job_root = self._job_root(job_id)
        lock_path = job_root / ".runner-state.lock"
        try:
            with lock_path.open("a+b") as lock_stream:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
                current = self._load_path(job_root / "runner-state.json", job_id)
                updated = mutate(current)
                atomic_write_json(job_root / "runner-state.json", self._serialize(updated))
                return updated
        except ApplicationError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise revision_error("IO_FAILURE", {"job_id": job_id}) from error

    def _load_locked(self, job_id: str) -> RunnerLeaseDto | None:
        job_root = self._job_root(job_id)
        try:
            with (job_root / ".runner-state.lock").open("a+b") as lock_stream:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_SH)
                return self._load_path(job_root / "runner-state.json", job_id)
        except ApplicationError:
            raise
        except OSError as error:
            raise revision_error("IO_FAILURE", {"job_id": job_id}) from error

    def _job_root(self, job_id: str) -> Path:
        try:
            DocumentJob(job_id)
        except ValueError as error:
            raise revision_error("INVALID_JOB_ID", {"job_id": job_id}) from error
        candidate = self._jobs_root / job_id
        if is_link_or_reparse(candidate):
            raise revision_error("LINK_NOT_ALLOWED", {"job_id": job_id})
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise revision_error("JOB_NOT_FOUND", {"job_id": job_id}) from error
        if not resolved.is_dir() or not is_within(resolved, self._jobs_root):
            raise revision_error("PATH_ESCAPE", {"job_id": job_id})
        return resolved

    def _load_path(self, path: Path, job_id: str) -> RunnerLeaseDto | None:
        if not path.exists():
            return None
        if is_link_or_reparse(path):
            raise revision_error("LINK_NOT_ALLOWED", {"job_id": job_id})
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or set(value) != {
                "schema_version",
                "job_id",
                "runner_token",
                "launch_sequence",
                "process_id",
                "lifecycle",
                "started_at",
                "heartbeat_at",
                "finished_at",
                "error_code",
            }:
                raise ValueError("runner state fields are invalid")
            if value["schema_version"] != 1 or value["job_id"] != job_id:
                raise ValueError("runner state identity is invalid")
            return RunnerLeaseDto(
                job_id=str(value["job_id"]),
                runner_token=str(value["runner_token"]),
                launch_sequence=int(value["launch_sequence"]),
                process_id=(
                    None if value["process_id"] is None else int(value["process_id"])
                ),
                lifecycle=RunnerLifecycle(str(value["lifecycle"])),
                started_at=self._datetime(value["started_at"]),
                heartbeat_at=self._datetime(value["heartbeat_at"]),
                finished_at=(
                    None
                    if value["finished_at"] is None
                    else self._datetime(value["finished_at"])
                ),
                error_code=(
                    None if value["error_code"] is None else str(value["error_code"])
                ),
            )
        except ApplicationError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise revision_error("RUNNER_LEASE_INVALID", {"job_id": job_id}) from error

    @staticmethod
    def _require_owner(
        current: RunnerLeaseDto | None,
        runner_token: str,
    ) -> RunnerLeaseDto:
        if current is None or current.runner_token != runner_token:
            raise revision_error(
                "RUNNER_LEASE_CONFLICT",
                {"job_id": None if current is None else current.job_id},
            )
        return current

    @staticmethod
    def _require_monotonic(
        current: RunnerLeaseDto,
        occurred_at: datetime,
        job_id: str,
    ) -> None:
        if occurred_at < current.heartbeat_at:
            raise revision_error("RUNNER_LEASE_CONFLICT", {"job_id": job_id})

    @staticmethod
    def _datetime(value: Any) -> datetime:
        if not isinstance(value, str):
            raise ValueError("runner timestamp must be a string")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("runner timestamp must include a timezone")
        return parsed

    @staticmethod
    def _serialize(lease: RunnerLeaseDto) -> dict[str, object]:
        def timestamp(value: datetime | None) -> str | None:
            if value is None:
                return None
            return value.isoformat().replace("+00:00", "Z")

        return {
            "schema_version": 1,
            "job_id": lease.job_id,
            "runner_token": lease.runner_token,
            "launch_sequence": lease.launch_sequence,
            "process_id": lease.process_id,
            "lifecycle": lease.lifecycle.value,
            "started_at": timestamp(lease.started_at),
            "heartbeat_at": timestamp(lease.heartbeat_at),
            "finished_at": timestamp(lease.finished_at),
            "error_code": lease.error_code,
        }
