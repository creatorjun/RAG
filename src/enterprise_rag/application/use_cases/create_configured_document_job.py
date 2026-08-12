from __future__ import annotations

import hashlib
import json
from pathlib import Path

from enterprise_rag.application.dto.jobs import (
    CreateDocumentJobDto,
    DocumentJobDto,
    JobExecutionSettingsDto,
)
from enterprise_rag.application.ports.desktop_settings_repository import (
    DesktopSettingsRepositoryPort,
)
from enterprise_rag.application.use_cases.create_document_job import CreateDocumentJob
from enterprise_rag.application.use_cases.model_catalog import InspectModelSelection
from enterprise_rag.domain.errors import revision_error

_BASE_PROMPT_POLICY_VERSION = "evidence-task-policy-v1"


class CreateConfiguredDocumentJob:
    def __init__(
        self,
        settings: DesktopSettingsRepositoryPort,
        create_job: CreateDocumentJob,
        deployment_fingerprint: str,
        model_selection: InspectModelSelection,
    ) -> None:
        if len(deployment_fingerprint) != 64:
            raise ValueError("deployment fingerprint must be SHA-256")
        self._settings = settings
        self._create_job = create_job
        self._deployment_fingerprint = deployment_fingerprint
        self._model_selection = model_selection

    async def execute(
        self,
        instruction: str,
        output_relative_path: str,
        source_root: str | None = None,
    ) -> DocumentJobDto:
        desktop = await self._settings.load()
        await self._model_selection.validate_for_job(
            desktop.model_id,
            desktop.model_revision,
            desktop.offline_mode,
        )
        selected_source_path = Path(source_root or desktop.source_root).expanduser()
        if not selected_source_path.is_absolute():
            raise revision_error("INVALID_INPUT", {"field": "source_root"})
        selected_source = str(selected_source_path.resolve(strict=False))
        prompt_fingerprint = self._digest(
            {
                "base_prompt_policy_version": _BASE_PROMPT_POLICY_VERSION,
                "additional_system_prompt": desktop.additional_system_prompt,
            }
        )
        execution = JobExecutionSettingsDto(
            output_root=desktop.output_root,
            model_id=desktop.model_id,
            model_revision=desktop.model_revision,
            context_tokens=desktop.context_tokens,
            max_output_tokens=desktop.max_output_tokens,
            additional_system_prompt=desktop.additional_system_prompt,
            prompt_fingerprint=prompt_fingerprint,
            max_task_attempts=desktop.max_task_attempts,
            offline_mode=desktop.offline_mode,
            notify_on_completion=desktop.notify_on_completion,
        )
        pipeline_fingerprint = self._digest(
            {
                "deployment_fingerprint": self._deployment_fingerprint,
                "source_root": selected_source,
                "output_root": execution.output_root,
                "output_relative_path": output_relative_path,
                "instruction": instruction,
                "model_id": execution.model_id,
                "model_revision": execution.model_revision,
                "context_tokens": execution.context_tokens,
                "max_output_tokens": execution.max_output_tokens,
                "prompt_fingerprint": execution.prompt_fingerprint,
                "max_task_attempts": execution.max_task_attempts,
                "offline_mode": execution.offline_mode,
                "notify_on_completion": execution.notify_on_completion,
            }
        )
        try:
            request = CreateDocumentJobDto(
                source_root=selected_source,
                instruction=instruction,
                output_relative_path=output_relative_path,
                pipeline_fingerprint=pipeline_fingerprint,
                execution_settings=execution,
            )
        except ValueError as error:
            raise revision_error("INVALID_INPUT") from error
        return await self._create_job.execute(request)

    @staticmethod
    def _digest(value: dict[str, object]) -> str:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
