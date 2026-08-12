from __future__ import annotations

import asyncio
import unittest

from enterprise_rag.application.dto.desktop_settings import DesktopSettingsDto
from enterprise_rag.application.dto.jobs import CreateDocumentJobDto, DocumentJobDto
from enterprise_rag.application.use_cases.create_configured_document_job import (
    CreateConfiguredDocumentJob,
)
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJobState


class _Settings:
    async def load(self) -> DesktopSettingsDto:
        return DesktopSettingsDto(
            4,
            "/workspace/source",
            "/workspace/output",
            "mlx-community/Qwen3.6-27B-4bit",
            "a" * 40,
            16_384,
            4_096,
            "경고를 반드시 보존한다.",
            2,
            True,
            True,
        )


class _CreateJob:
    def __init__(self) -> None:
        self.request: CreateDocumentJobDto | None = None

    async def execute(self, request: CreateDocumentJobDto) -> DocumentJobDto:
        self.request = request
        return DocumentJobDto("job-" + "b" * 32, DocumentJobState.CREATED, 0, 0)


class _Models:
    def __init__(self, error: ApplicationError | None = None) -> None:
        self.error = error
        self.arguments = None

    async def validate_for_job(self, *arguments):
        self.arguments = arguments
        if self.error is not None:
            raise self.error


class CreateConfiguredDocumentJobTest(unittest.TestCase):
    def test_freezes_desktop_model_prompt_and_policy_into_job_request(self) -> None:
        create = _CreateJob()
        models = _Models()
        use_case = CreateConfiguredDocumentJob(  # type: ignore[arg-type]
            _Settings(), create, "c" * 64, models
        )
        result = asyncio.run(use_case.execute("운영 문서 작성", "guide.md"))
        self.assertEqual(result.state, DocumentJobState.CREATED)
        self.assertIsNotNone(create.request)
        snapshot = create.request.execution_settings
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.model_revision, "a" * 40)
        self.assertEqual(snapshot.additional_system_prompt, "경고를 반드시 보존한다.")
        self.assertEqual(snapshot.max_task_attempts, 2)
        self.assertEqual(len(snapshot.prompt_fingerprint), 64)
        self.assertEqual(len(create.request.pipeline_fingerprint), 64)
        self.assertEqual(
            models.arguments,
            ("mlx-community/Qwen3.6-27B-4bit", "a" * 40, True),
        )
        first_fingerprint = create.request.pipeline_fingerprint
        asyncio.run(use_case.execute("다른 운영 문서 작성", "guide.md"))
        self.assertNotEqual(create.request.pipeline_fingerprint, first_fingerprint)

    def test_rejects_invalid_deployment_or_source_before_job_creation(self) -> None:
        with self.assertRaises(ValueError):
            CreateConfiguredDocumentJob(  # type: ignore[arg-type]
                _Settings(), _CreateJob(), "bad", _Models()
            )
        create = _CreateJob()
        use_case = CreateConfiguredDocumentJob(  # type: ignore[arg-type]
            _Settings(), create, "c" * 64, _Models()
        )
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(
                use_case.execute(
                    "운영 문서 작성",
                    "guide.md",
                    source_root="relative",
                )
            )
        self.assertEqual(captured.exception.code, "INVALID_INPUT")
        self.assertIsNone(create.request)


if __name__ == "__main__":
    unittest.main()
