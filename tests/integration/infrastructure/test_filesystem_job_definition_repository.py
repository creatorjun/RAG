from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from enterprise_rag.application.dto.jobs import (
    CreateDocumentJobDto,
    JobExecutionSettingsDto,
)
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.jobs.filesystem_job_artifact_repository import (
    FilesystemJobArtifactRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_job_definition_repository import (
    FilesystemDocumentJobDefinitionRepository,
)


class FilesystemDocumentJobDefinitionRepositoryTest(unittest.TestCase):
    def test_round_trips_configured_job_definition_and_rejects_legacy_definition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            artifacts = FilesystemJobArtifactRepository(root / "var")
            repository = FilesystemDocumentJobDefinitionRepository(artifacts)
            execution = JobExecutionSettingsDto(
                str(root / "output"),
                "mlx-community/Qwen3.6-27B-4bit",
                "a" * 40,
                16_384,
                4_096,
                "경고 보존",
                "b" * 64,
                2,
                True,
                True,
            )
            configured = DocumentJob("job-" + "c" * 32)
            request = CreateDocumentJobDto(
                str(root / "source"),
                "운영 문서 작성",
                "guide.md",
                "d" * 64,
                execution,
            )
            asyncio.run(artifacts.initialize(configured, request))
            restored = asyncio.run(repository.load(configured.job_id))
            self.assertEqual(restored.request, request)

            legacy = DocumentJob("job-" + "e" * 32)
            asyncio.run(
                artifacts.initialize(
                    legacy,
                    CreateDocumentJobDto(
                        str(root / "source"),
                        "운영 문서 작성",
                        "guide.md",
                        "f" * 64,
                    ),
                )
            )
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.load(legacy.job_id))
            self.assertEqual(captured.exception.code, "JOB_DEFINITION_INVALID")


if __name__ == "__main__":
    unittest.main()
