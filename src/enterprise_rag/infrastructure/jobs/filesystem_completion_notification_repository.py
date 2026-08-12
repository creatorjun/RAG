from __future__ import annotations

import asyncio
import fcntl
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from enterprise_rag.application.dto.job_result import (
    CompletionNotificationClaimDto,
    CompletionNotificationDto,
    CompletionNotificationState,
)
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.workspace.file_io import atomic_write_json
from enterprise_rag.infrastructure.workspace.path_security import (
    is_link_or_reparse,
    is_within,
)

_RECEIPT = "control/completion-notification.json"
_LOCK = ".completion-notification.lock"


class FilesystemCompletionNotificationRepository:
    def __init__(self, var_root: Path) -> None:
        self._jobs_root = (var_root / "jobs").resolve(strict=True)

    async def get(self, job_id: str) -> CompletionNotificationDto | None:
        return await asyncio.to_thread(self._get, job_id)

    async def claim(
        self,
        job_id: str,
        publication_fingerprint: str,
        occurred_at: datetime,
    ) -> CompletionNotificationClaimDto:
        return await asyncio.to_thread(
            self._claim,
            job_id,
            publication_fingerprint,
            occurred_at,
        )

    async def finish(
        self,
        job_id: str,
        publication_fingerprint: str,
        occurred_at: datetime,
        error_code: str | None = None,
    ) -> CompletionNotificationDto:
        return await asyncio.to_thread(
            self._finish,
            job_id,
            publication_fingerprint,
            occurred_at,
            error_code,
        )

    def _get(self, job_id: str) -> CompletionNotificationDto | None:
        job_root = self._job_root(job_id)
        try:
            with (job_root / _LOCK).open("a+b") as lock_stream:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_SH)
                return self._load(job_root, job_id)
        except ApplicationError:
            raise
        except OSError as error:
            raise revision_error(
                "NOTIFICATION_RECEIPT_INVALID", {"job_id": job_id}
            ) from error

    def _claim(
        self,
        job_id: str,
        publication_fingerprint: str,
        occurred_at: datetime,
    ) -> CompletionNotificationClaimDto:
        job_root = self._job_root(job_id)
        try:
            with (job_root / _LOCK).open("a+b") as lock_stream:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
                existing = self._load(job_root, job_id)
                if existing is not None:
                    if existing.publication_fingerprint != publication_fingerprint:
                        raise revision_error(
                            "NOTIFICATION_RECEIPT_INVALID", {"job_id": job_id}
                        )
                    return CompletionNotificationClaimDto(existing, False)
                claimed = CompletionNotificationDto(
                    job_id,
                    CompletionNotificationState.CLAIMED,
                    publication_fingerprint,
                    occurred_at,
                )
                atomic_write_json(job_root / _RECEIPT, self._serialize(claimed))
                return CompletionNotificationClaimDto(claimed, True)
        except ApplicationError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise revision_error(
                "NOTIFICATION_RECEIPT_INVALID", {"job_id": job_id}
            ) from error

    def _finish(
        self,
        job_id: str,
        publication_fingerprint: str,
        occurred_at: datetime,
        error_code: str | None,
    ) -> CompletionNotificationDto:
        job_root = self._job_root(job_id)
        try:
            with (job_root / _LOCK).open("a+b") as lock_stream:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
                existing = self._load(job_root, job_id)
                if (
                    existing is None
                    or existing.publication_fingerprint != publication_fingerprint
                ):
                    raise revision_error(
                        "NOTIFICATION_RECEIPT_INVALID", {"job_id": job_id}
                    )
                target = (
                    CompletionNotificationState.FAILED
                    if error_code is not None
                    else CompletionNotificationState.DELIVERED
                )
                if existing.state is not CompletionNotificationState.CLAIMED:
                    if existing.state is target and existing.error_code == error_code:
                        return existing
                    raise revision_error(
                        "NOTIFICATION_RECEIPT_INVALID", {"job_id": job_id}
                    )
                if existing.claimed_at is None or occurred_at < existing.claimed_at:
                    raise revision_error(
                        "NOTIFICATION_RECEIPT_INVALID", {"job_id": job_id}
                    )
                finished = CompletionNotificationDto(
                    job_id,
                    target,
                    publication_fingerprint,
                    existing.claimed_at,
                    occurred_at,
                    error_code,
                )
                atomic_write_json(job_root / _RECEIPT, self._serialize(finished))
                return finished
        except ApplicationError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise revision_error(
                "NOTIFICATION_RECEIPT_INVALID", {"job_id": job_id}
            ) from error

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
    def _load(
        cls,
        job_root: Path,
        job_id: str,
    ) -> CompletionNotificationDto | None:
        path = job_root / _RECEIPT
        if not path.exists():
            return None
        if is_link_or_reparse(path):
            raise revision_error("LINK_NOT_ALLOWED", {"job_id": job_id})
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or set(value) != {
                "schema_version",
                "job_id",
                "state",
                "publication_fingerprint",
                "claimed_at",
                "finished_at",
                "error_code",
            }:
                raise ValueError("invalid notification receipt fields")
            if value["schema_version"] != 1 or value["job_id"] != job_id:
                raise ValueError("invalid notification receipt identity")
            state = CompletionNotificationState(cls._string(value["state"]))
            if state not in {
                CompletionNotificationState.CLAIMED,
                CompletionNotificationState.DELIVERED,
                CompletionNotificationState.FAILED,
            }:
                raise ValueError("invalid persisted notification state")
            return CompletionNotificationDto(
                job_id,
                state,
                cls._string(value["publication_fingerprint"]),
                cls._datetime(value["claimed_at"]),
                cls._optional_datetime(value["finished_at"]),
                cls._optional_string(value["error_code"]),
            )
        except ApplicationError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise revision_error(
                "NOTIFICATION_RECEIPT_INVALID", {"job_id": job_id}
            ) from error

    @staticmethod
    def _serialize(receipt: CompletionNotificationDto) -> dict[str, object]:
        def timestamp(value: datetime | None) -> str | None:
            return None if value is None else value.isoformat().replace("+00:00", "Z")

        return {
            "schema_version": 1,
            "job_id": receipt.job_id,
            "state": receipt.state.value,
            "publication_fingerprint": receipt.publication_fingerprint,
            "claimed_at": timestamp(receipt.claimed_at),
            "finished_at": timestamp(receipt.finished_at),
            "error_code": receipt.error_code,
        }

    @staticmethod
    def _string(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("expected string")
        return value

    @classmethod
    def _optional_string(cls, value: Any) -> str | None:
        return None if value is None else cls._string(value)

    @classmethod
    def _datetime(cls, value: Any) -> datetime:
        parsed = datetime.fromisoformat(cls._string(value).replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("notification timestamp must include a timezone")
        return parsed

    @classmethod
    def _optional_datetime(cls, value: Any) -> datetime | None:
        return None if value is None else cls._datetime(value)
