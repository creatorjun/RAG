from __future__ import annotations

import asyncio
import fcntl
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from enterprise_rag.application.dto.model_stream import (
    ModelStreamEventDto,
    ModelStreamEventKind,
    ModelStreamSnapshotDto,
)
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.workspace.path_security import (
    is_link_or_reparse,
    is_within,
)

_STREAM_PATH = "runtime/model-stream.jsonl"


class FilesystemModelStreamRepository:
    def __init__(self, var_root: Path) -> None:
        if is_link_or_reparse(var_root):
            raise revision_error("LINK_NOT_ALLOWED")
        try:
            var_root.mkdir(parents=True, exist_ok=True)
            self._jobs_root = var_root.expanduser().resolve(strict=True) / "jobs"
            self._jobs_root.mkdir(exist_ok=True)
        except OSError as error:
            raise revision_error("IO_FAILURE") from error

    def append(self, event: ModelStreamEventDto) -> None:
        job_root = self._job_root(event.job_id)
        runtime_root = job_root / "runtime"
        lock_path = job_root / ".model-stream.lock"
        try:
            runtime_root.mkdir(exist_ok=True)
            if is_link_or_reparse(runtime_root) or is_link_or_reparse(lock_path):
                raise revision_error("LINK_NOT_ALLOWED", {"job_id": event.job_id})
            with lock_path.open("a+b") as lock_stream:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
                stream_path = job_root / _STREAM_PATH
                latest = self._latest_sequence(stream_path, event.job_id)
                if event.sequence != latest + 1:
                    raise revision_error(
                        "PROGRESS_EVENT_CONFLICT",
                        {"job_id": event.job_id},
                    )
                with stream_path.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(
                        json.dumps(
                            self._serialize(event),
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
        except ApplicationError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise revision_error("IO_FAILURE", {"job_id": event.job_id}) from error

    async def snapshot(
        self,
        job_id: str,
        limit: int = 1_000,
    ) -> ModelStreamSnapshotDto:
        if not 1 <= limit <= 10_000:
            raise ValueError("model stream limit is invalid")
        return await asyncio.to_thread(self._snapshot, job_id, limit)

    def next_sequence(self, job_id: str) -> int:
        job_root = self._job_root(job_id)
        lock_path = job_root / ".model-stream.lock"
        try:
            if is_link_or_reparse(lock_path):
                raise revision_error("LINK_NOT_ALLOWED", {"job_id": job_id})
            with lock_path.open("a+b") as lock_stream:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_SH)
                return self._latest_sequence(job_root / _STREAM_PATH, job_id) + 1
        except ApplicationError:
            raise
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as error:
            raise revision_error("IO_FAILURE", {"job_id": job_id}) from error

    def _snapshot(self, job_id: str, limit: int) -> ModelStreamSnapshotDto:
        job_root = self._job_root(job_id)
        lock_path = job_root / ".model-stream.lock"
        try:
            if is_link_or_reparse(lock_path):
                raise revision_error("LINK_NOT_ALLOWED", {"job_id": job_id})
            with lock_path.open("a+b") as lock_stream:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_SH)
                path = job_root / _STREAM_PATH
                if not path.exists():
                    return ModelStreamSnapshotDto()
                if is_link_or_reparse(path):
                    raise revision_error("LINK_NOT_ALLOWED", {"job_id": job_id})
                values = [
                    self._deserialize(json.loads(line), job_id)
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line
                ]
            latest = values[-1].sequence if values else 0
            selected = tuple(values[-limit:])
            return ModelStreamSnapshotDto(
                selected,
                latest,
                len(values) > len(selected),
            )
        except ApplicationError:
            raise
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
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

    @classmethod
    def _latest_sequence(cls, path: Path, job_id: str) -> int:
        if not path.exists():
            return 0
        if is_link_or_reparse(path):
            raise revision_error("LINK_NOT_ALLOWED", {"job_id": job_id})
        line = cls._last_line(path)
        if not line:
            return 0
        value = json.loads(line)
        if not isinstance(value, dict) or value.get("job_id") != job_id:
            raise ValueError("model stream tail is invalid")
        sequence = value.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ValueError("model stream sequence is invalid")
        return sequence

    @staticmethod
    def _last_line(path: Path) -> str:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            position = stream.tell()
            buffered = b""
            while position > 0:
                chunk_size = min(position, 8_192)
                position -= chunk_size
                stream.seek(position)
                buffered = stream.read(chunk_size) + buffered
                stripped = buffered.rstrip(b"\r\n")
                if b"\n" in stripped or position == 0:
                    return stripped.rsplit(b"\n", 1)[-1].decode("utf-8")
        return ""

    @staticmethod
    def _serialize(event: ModelStreamEventDto) -> dict[str, object]:
        return {
            "schema_version": 1,
            "job_id": event.job_id,
            "sequence": event.sequence,
            "generation_id": event.generation_id,
            "stage": event.stage,
            "kind": event.kind.value,
            "text": event.text,
            "occurred_at": event.occurred_at.isoformat().replace("+00:00", "Z"),
            "error_code": event.error_code,
        }

    @staticmethod
    def _deserialize(value: Any, job_id: str) -> ModelStreamEventDto:
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "job_id",
            "sequence",
            "generation_id",
            "stage",
            "kind",
            "text",
            "occurred_at",
            "error_code",
        }:
            raise ValueError("model stream fields are invalid")
        if value["schema_version"] != 1 or value["job_id"] != job_id:
            raise ValueError("model stream identity is invalid")
        occurred_at = datetime.fromisoformat(str(value["occurred_at"]).replace("Z", "+00:00"))
        error_code = value["error_code"]
        return ModelStreamEventDto(
            job_id=job_id,
            sequence=int(value["sequence"]),
            generation_id=str(value["generation_id"]),
            stage=str(value["stage"]),
            kind=ModelStreamEventKind(str(value["kind"])),
            text=str(value["text"]),
            occurred_at=occurred_at,
            error_code=None if error_code is None else str(error_code),
        )
