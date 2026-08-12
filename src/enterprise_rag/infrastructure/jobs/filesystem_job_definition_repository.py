from __future__ import annotations

from typing import Any

from enterprise_rag.application.dto.jobs import (
    CreateDocumentJobDto,
    JobExecutionSettingsDto,
    StoredDocumentJobDefinitionDto,
)
from enterprise_rag.application.ports.job_artifacts import JobArtifactRepositoryPort
from enterprise_rag.domain.errors import revision_error


class FilesystemDocumentJobDefinitionRepository:
    def __init__(self, artifacts: JobArtifactRepositoryPort) -> None:
        self._artifacts = artifacts

    async def load(self, job_id: str) -> StoredDocumentJobDefinitionDto:
        value = await self._artifacts.read_json(job_id, "definition.json")
        try:
            if value.get("schema_version") != 1 or value.get("job_id") != job_id:
                raise ValueError("invalid job definition envelope")
            execution = self._mapping(value["execution_settings"])
            request = CreateDocumentJobDto(
                source_root=self._string(value["source_root"]),
                instruction=self._string(value["instruction"]),
                output_relative_path=self._string(value["output_relative_path"]),
                pipeline_fingerprint=self._string(value["pipeline_fingerprint"]),
                execution_settings=JobExecutionSettingsDto(
                    output_root=self._string(execution["output_root"]),
                    model_id=self._string(execution["model_id"]),
                    model_revision=self._string(execution["model_revision"]),
                    context_tokens=self._integer(execution["context_tokens"]),
                    max_output_tokens=self._integer(execution["max_output_tokens"]),
                    additional_system_prompt=self._string(
                        execution["additional_system_prompt"]
                    ),
                    prompt_fingerprint=self._string(execution["prompt_fingerprint"]),
                    max_task_attempts=self._integer(execution["max_task_attempts"]),
                    offline_mode=self._boolean(execution["offline_mode"]),
                    notify_on_completion=self._boolean(
                        execution["notify_on_completion"]
                    ),
                ),
            )
            return StoredDocumentJobDefinitionDto(job_id, request)
        except (KeyError, TypeError, ValueError) as error:
            raise revision_error("JOB_DEFINITION_INVALID", {"job_id": job_id}) from error

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("expected object")
        return value

    @staticmethod
    def _string(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("expected string")
        return value

    @staticmethod
    def _integer(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("expected integer")
        return int(value)

    @staticmethod
    def _boolean(value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("expected boolean")
        return value
