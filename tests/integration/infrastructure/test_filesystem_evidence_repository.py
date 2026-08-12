from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from enterprise_rag.application.dto.evidence import EvidenceBundleDto, EvidenceItemDto
from enterprise_rag.application.dto.jobs import CreateDocumentJobDto
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.jobs.filesystem_evidence_repository import (
    FilesystemEvidenceRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_job_artifact_repository import (
    FilesystemJobArtifactRepository,
)


class FilesystemEvidenceRepositoryTest(unittest.TestCase):
    def test_round_trips_write_once_evidence_in_dedicated_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            artifacts = FilesystemJobArtifactRepository(root / "var")
            job = DocumentJob("job-" + "a" * 32)
            definition = CreateDocumentJobDto(
                str(root),
                "문서 작성",
                "integrated.md",
                "b" * 64,
            )
            asyncio.run(artifacts.initialize(job, definition))
            item = EvidenceItemDto(
                evidence_id="evidence:sha256:" + "c" * 64,
                chunk_id="chunk:1",
                revision_id="revision:1",
                relative_path="guide.md",
                source_sha256="d" * 64,
                ordinal=0,
                start_char=0,
                end_char=4,
                content_sha256="e" * 64,
                text="text",
            )
            bundle = EvidenceBundleDto((item,), 1, 1)
            repository = FilesystemEvidenceRepository(artifacts)
            path = asyncio.run(repository.save(job.job_id, bundle))
            restored = asyncio.run(repository.load(job.job_id))
            self.assertEqual(path, "evidence/index.json")
            self.assertEqual(restored, bundle)
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.save(job.job_id, bundle))
            self.assertEqual(captured.exception.code, "JOB_ARTIFACT_ALREADY_EXISTS")


if __name__ == "__main__":
    unittest.main()
