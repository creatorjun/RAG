from __future__ import annotations

import re
from typing import Any

from enterprise_rag.application.dto.tasks import (
    TaskOutputDto,
    TaskSectionOutputDto,
    TaskValidationReportDto,
)
from enterprise_rag.application.ports.job_artifacts import JobArtifactRepositoryPort
from enterprise_rag.domain.errors import revision_error

_TASK_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")


class FilesystemTaskResultRepository:
    def __init__(self, artifacts: JobArtifactRepositoryPort) -> None:
        self._artifacts = artifacts

    async def save_output(
        self,
        job_id: str,
        attempt: int,
        output: TaskOutputDto,
    ) -> str:
        return await self._artifacts.write_json_once(
            job_id,
            self._path(output.task_id, attempt, "output.json"),
            {
                "schema_version": 1,
                "job_id": job_id,
                "attempt": attempt,
                "task_id": output.task_id,
                "completion_marker": output.completion_marker,
                "conflict_claim_ids": list(output.conflict_claim_ids),
                "sections": [
                    {
                        "section_key": section.section_key,
                        "heading": section.heading,
                        "markdown": section.markdown,
                        "used_claim_ids": list(section.used_claim_ids),
                        "used_evidence_ids": list(section.used_evidence_ids),
                    }
                    for section in output.sections
                ],
            },
        )

    async def load_output(
        self,
        job_id: str,
        task_id: str,
        attempt: int,
    ) -> TaskOutputDto:
        value = await self._artifacts.read_json(
            job_id,
            self._path(task_id, attempt, "output.json"),
        )
        try:
            self._validate_envelope(value, job_id, task_id, attempt)
            return TaskOutputDto(
                task_id=task_id,
                sections=tuple(
                    self._section(item) for item in self._list(value["sections"])
                ),
                conflict_claim_ids=self._strings(value["conflict_claim_ids"]),
                completion_marker=str(value["completion_marker"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise revision_error("TASK_OUTPUT_INVALID", {"task_id": task_id}) from error

    async def save_validation(
        self,
        job_id: str,
        attempt: int,
        report: TaskValidationReportDto,
    ) -> str:
        return await self._artifacts.write_json_once(
            job_id,
            self._path(report.task_id, attempt, "validation.json"),
            {
                "schema_version": 1,
                "job_id": job_id,
                "attempt": attempt,
                "task_id": report.task_id,
                "valid": report.valid,
                "error_codes": list(report.error_codes),
            },
        )

    async def load_validation(
        self,
        job_id: str,
        task_id: str,
        attempt: int,
    ) -> TaskValidationReportDto:
        value = await self._artifacts.read_json(
            job_id,
            self._path(task_id, attempt, "validation.json"),
        )
        try:
            self._validate_envelope(value, job_id, task_id, attempt)
            valid = value["valid"]
            if not isinstance(valid, bool):
                raise ValueError("invalid validation status")
            return TaskValidationReportDto(
                task_id=task_id,
                valid=valid,
                error_codes=self._strings(value["error_codes"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise revision_error("TASK_OUTPUT_INVALID", {"task_id": task_id}) from error

    @classmethod
    def _path(cls, task_id: str, attempt: int, filename: str) -> str:
        if not _TASK_ID_PATTERN.fullmatch(task_id) or not 1 <= attempt <= 999:
            raise revision_error("TASK_OUTPUT_INVALID", {"task_id": task_id})
        return f"tasks/{task_id}/attempt-{attempt:03d}/{filename}"

    @staticmethod
    def _validate_envelope(
        value: dict[str, Any],
        job_id: str,
        task_id: str,
        attempt: int,
    ) -> None:
        if (
            value.get("schema_version") != 1
            or value.get("job_id") != job_id
            or value.get("task_id") != task_id
            or value.get("attempt") != attempt
        ):
            raise ValueError("invalid task result envelope")

    @classmethod
    def _section(cls, value: Any) -> TaskSectionOutputDto:
        item = cls._mapping(value)
        return TaskSectionOutputDto(
            section_key=str(item["section_key"]),
            heading=str(item["heading"]),
            markdown=str(item["markdown"]),
            used_claim_ids=cls._strings(item["used_claim_ids"]),
            used_evidence_ids=cls._strings(item["used_evidence_ids"]),
        )

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("expected object")
        return value

    @staticmethod
    def _list(value: Any) -> list[Any]:
        if not isinstance(value, list):
            raise ValueError("expected list")
        return value

    @classmethod
    def _strings(cls, value: Any) -> tuple[str, ...]:
        values = cls._list(value)
        if any(not isinstance(item, str) for item in values):
            raise ValueError("expected strings")
        return tuple(values)
