from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from enterprise_rag.application.dto.jobs import CreateDocumentJobDto
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.workspace.file_io import atomic_write_json
from enterprise_rag.infrastructure.workspace.path_security import is_link_or_reparse, is_within


class FilesystemJobArtifactRepository:
    def __init__(self, var_root: Path) -> None:
        if is_link_or_reparse(var_root):
            raise revision_error("LINK_NOT_ALLOWED")
        try:
            var_root.mkdir(parents=True, exist_ok=True)
            self._var_root = var_root.expanduser().resolve(strict=True)
            self._jobs_root = self._var_root / "jobs"
            self._staging_root = self._var_root / ".job-staging"
            self._jobs_root.mkdir(exist_ok=True)
            self._staging_root.mkdir(exist_ok=True)
        except OSError as error:
            raise revision_error("IO_FAILURE") from error

    async def initialize(
        self,
        job: DocumentJob,
        definition: CreateDocumentJobDto,
    ) -> None:
        await asyncio.to_thread(
            self._initialize,
            job,
            definition,
        )

    async def write_json_once(
        self,
        job_id: str,
        relative_path: str,
        value: Mapping[str, object],
    ) -> str:
        return await asyncio.to_thread(
            self._write_json_once,
            job_id,
            relative_path,
            value,
        )

    async def read_json(self, job_id: str, relative_path: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._read_json, job_id, relative_path)

    async def write_text_once(
        self,
        job_id: str,
        relative_path: str,
        value: str,
    ) -> str:
        return await asyncio.to_thread(
            self._write_text_once,
            job_id,
            relative_path,
            value,
        )

    async def read_text(self, job_id: str, relative_path: str) -> str:
        return await asyncio.to_thread(self._read_text, job_id, relative_path)

    async def list_relative_paths(
        self,
        job_id: str,
        prefix: str | None = None,
    ) -> tuple[str, ...]:
        return await asyncio.to_thread(self._list_relative_paths, job_id, prefix)

    def _initialize(
        self,
        job: DocumentJob,
        definition: CreateDocumentJobDto,
    ) -> None:
        target = self._jobs_root / job.job_id
        if target.exists() or is_link_or_reparse(target):
            raise revision_error("JOB_ARTIFACT_ALREADY_EXISTS", {"job_id": job.job_id})
        temporary = self._staging_root / f"{job.job_id}-{uuid4().hex}"
        try:
            temporary.mkdir(parents=False, exist_ok=False)
            atomic_write_json(
                temporary / "job.json",
                {
                    "schema_version": 1,
                    "job_id": job.job_id,
                    "state": job.state.value,
                    "last_event_sequence": job.last_event_sequence,
                    "last_percentage": job.last_percentage,
                    "pipeline_fingerprint": definition.pipeline_fingerprint,
                },
            )
            atomic_write_json(
                temporary / "definition.json",
                {
                    "schema_version": 1,
                    "job_id": job.job_id,
                    "source_root": definition.source_root,
                    "instruction": definition.instruction,
                    "output_relative_path": definition.output_relative_path,
                    "pipeline_fingerprint": definition.pipeline_fingerprint,
                    "execution_settings": self._execution_settings(definition),
                },
            )
            try:
                temporary.rename(target)
            except FileExistsError as error:
                raise revision_error(
                    "JOB_ARTIFACT_ALREADY_EXISTS",
                    {"job_id": job.job_id},
                ) from error
        except ApplicationError:
            raise
        except (OSError, TypeError, ValueError) as error:
            raise revision_error("IO_FAILURE", {"job_id": job.job_id}) from error
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def _write_json_once(
        self,
        job_id: str,
        relative_path: str,
        value: Mapping[str, object],
    ) -> str:
        job_root = self._job_root(job_id)
        relative = self._validated_relative_path(relative_path, {".json"})
        target = job_root.joinpath(*relative.parts)
        self._validate_parent_chain(job_root, relative)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            resolved_parent = target.parent.resolve(strict=True)
            if not is_within(resolved_parent, job_root):
                raise revision_error("PATH_ESCAPE", {"relative_path": relative_path})
            self._atomic_create_json(target, value)
        except ApplicationError:
            raise
        except FileExistsError as error:
            raise revision_error(
                "JOB_ARTIFACT_ALREADY_EXISTS",
                {"job_id": job_id, "relative_path": relative_path},
            ) from error
        except (OSError, TypeError, ValueError) as error:
            raise revision_error("IO_FAILURE", {"job_id": job_id}) from error
        return relative.as_posix()

    def _read_json(self, job_id: str, relative_path: str) -> dict[str, Any]:
        job_root = self._job_root(job_id)
        relative = self._validated_relative_path(relative_path, {".json"})
        target = job_root.joinpath(*relative.parts)
        if is_link_or_reparse(target):
            raise revision_error("LINK_NOT_ALLOWED", {"relative_path": relative_path})
        try:
            resolved = target.resolve(strict=True)
            if not is_within(resolved, job_root) or not resolved.is_file():
                raise revision_error("PATH_ESCAPE", {"relative_path": relative_path})
            value = json.loads(resolved.read_text(encoding="utf-8"))
        except ApplicationError:
            raise
        except FileNotFoundError as error:
            raise revision_error(
                "JOB_ARTIFACT_NOT_FOUND",
                {"job_id": job_id, "relative_path": relative_path},
            ) from error
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise revision_error("IO_FAILURE", {"job_id": job_id}) from error
        if not isinstance(value, dict):
            raise revision_error("IO_FAILURE", {"job_id": job_id})
        return value

    def _write_text_once(
        self,
        job_id: str,
        relative_path: str,
        value: str,
    ) -> str:
        if not value:
            raise revision_error("IO_FAILURE", {"job_id": job_id})
        job_root = self._job_root(job_id)
        relative = self._validated_relative_path(relative_path, {".md"})
        target = job_root.joinpath(*relative.parts)
        self._validate_parent_chain(job_root, relative)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            resolved_parent = target.parent.resolve(strict=True)
            if not is_within(resolved_parent, job_root):
                raise revision_error("PATH_ESCAPE", {"relative_path": relative_path})
            self._atomic_create_text(target, value)
        except ApplicationError:
            raise
        except FileExistsError as error:
            raise revision_error(
                "JOB_ARTIFACT_ALREADY_EXISTS",
                {"job_id": job_id, "relative_path": relative_path},
            ) from error
        except (OSError, UnicodeError, ValueError) as error:
            raise revision_error("IO_FAILURE", {"job_id": job_id}) from error
        return relative.as_posix()

    def _read_text(self, job_id: str, relative_path: str) -> str:
        job_root = self._job_root(job_id)
        relative = self._validated_relative_path(relative_path, {".md"})
        target = job_root.joinpath(*relative.parts)
        if is_link_or_reparse(target):
            raise revision_error("LINK_NOT_ALLOWED", {"relative_path": relative_path})
        try:
            resolved = target.resolve(strict=True)
            if not is_within(resolved, job_root) or not resolved.is_file():
                raise revision_error("PATH_ESCAPE", {"relative_path": relative_path})
            return resolved.read_text(encoding="utf-8")
        except ApplicationError:
            raise
        except FileNotFoundError as error:
            raise revision_error(
                "JOB_ARTIFACT_NOT_FOUND",
                {"job_id": job_id, "relative_path": relative_path},
            ) from error
        except (OSError, UnicodeDecodeError) as error:
            raise revision_error("IO_FAILURE", {"job_id": job_id}) from error

    def _list_relative_paths(
        self,
        job_id: str,
        prefix: str | None,
    ) -> tuple[str, ...]:
        job_root = self._job_root(job_id)
        scan_root = job_root
        if prefix is not None:
            relative_prefix = PurePosixPath(prefix)
            if (
                not prefix
                or relative_prefix.is_absolute()
                or any(part in {"", ".", ".."} for part in relative_prefix.parts)
            ):
                raise revision_error("PATH_ESCAPE", {"relative_path": prefix})
            scan_root = job_root.joinpath(*relative_prefix.parts)
            if not scan_root.exists():
                return ()
            if is_link_or_reparse(scan_root):
                raise revision_error("LINK_NOT_ALLOWED", {"relative_path": prefix})
        try:
            paths: list[str] = []
            for path in scan_root.rglob("*"):
                if is_link_or_reparse(path):
                    raise revision_error(
                        "LINK_NOT_ALLOWED",
                        {"relative_path": path.relative_to(job_root).as_posix()},
                    )
                if path.is_file():
                    paths.append(path.relative_to(job_root).as_posix())
            return tuple(sorted(paths))
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
        except FileNotFoundError as error:
            raise revision_error("JOB_ARTIFACT_NOT_FOUND", {"job_id": job_id}) from error
        if not resolved.is_dir() or not is_within(resolved, self._jobs_root):
            raise revision_error("PATH_ESCAPE", {"job_id": job_id})
        return resolved

    @staticmethod
    def _validated_relative_path(
        value: str,
        suffixes: set[str],
    ) -> PurePosixPath:
        relative = PurePosixPath(value)
        if (
            not value
            or value.startswith("/")
            or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.suffix not in suffixes
        ):
            raise revision_error("PATH_ESCAPE", {"relative_path": value})
        return relative

    @staticmethod
    def _validate_parent_chain(job_root: Path, relative: PurePosixPath) -> None:
        current = job_root
        for part in relative.parts[:-1]:
            current = current / part
            if current.exists() and is_link_or_reparse(current):
                raise revision_error(
                    "LINK_NOT_ALLOWED",
                    {"relative_path": relative.as_posix()},
                )

    @staticmethod
    def _atomic_create_json(target: Path, value: Mapping[str, object]) -> None:
        serialized = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        FilesystemJobArtifactRepository._atomic_create_text(target, serialized)

    @staticmethod
    def _atomic_create_text(target: Path, value: str) -> None:
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _execution_settings(definition: CreateDocumentJobDto) -> dict[str, object] | None:
        settings = definition.execution_settings
        if settings is None:
            return None
        return {
            "output_root": settings.output_root,
            "model_id": settings.model_id,
            "model_revision": settings.model_revision,
            "context_tokens": settings.context_tokens,
            "max_output_tokens": settings.max_output_tokens,
            "additional_system_prompt": settings.additional_system_prompt,
            "prompt_fingerprint": settings.prompt_fingerprint,
            "max_task_attempts": settings.max_task_attempts,
            "offline_mode": settings.offline_mode,
            "notify_on_completion": settings.notify_on_completion,
        }
