from __future__ import annotations

import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path

from enterprise_rag.application.dto.jobs import CreateDocumentJobDto
from enterprise_rag.application.dto.tasks import (
    FinalDocumentCandidateDto,
    FinalQualityReportDto,
)
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.jobs.filesystem_final_document_repository import (
    FilesystemFinalDocumentRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_job_artifact_repository import (
    FilesystemJobArtifactRepository,
)


def _candidate(markdown: str) -> FinalDocumentCandidateDto:
    return FinalDocumentCandidateDto(
        markdown,
        FinalQualityReportDto(
            valid=True,
            error_codes=(),
            document_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
            source_document_count=1,
            evidence_count=1,
            claim_count=1,
            task_count=1,
            validated_task_count=1,
            covered_claim_count=1,
            covered_evidence_count=1,
        ),
    )


class FilesystemFinalDocumentRepositoryTest(unittest.TestCase):
    def test_load_requires_both_draft_and_final_validation_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            artifacts = FilesystemJobArtifactRepository(root / "var")
            job = DocumentJob("job-" + "e" * 32)
            asyncio.run(
                artifacts.initialize(
                    job,
                    CreateDocumentJobDto(
                        str(root), "문서 작성", "output.md", "f" * 64
                    ),
                )
            )
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(FilesystemFinalDocumentRepository(artifacts).load(job.job_id))
            self.assertEqual(captured.exception.code, "FINAL_ARTIFACT_INVALID")

    def test_saves_loads_and_idempotently_verifies_final_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            artifacts = FilesystemJobArtifactRepository(root / "var")
            job = DocumentJob("job-" + "a" * 32)
            asyncio.run(
                artifacts.initialize(
                    job,
                    CreateDocumentJobDto(
                        str(root), "문서 작성", "output.md", "b" * 64
                    ),
                )
            )
            candidate = _candidate("# 문서\n\n내용 [source:guide.md]\n")
            repository = FilesystemFinalDocumentRepository(artifacts)
            paths = asyncio.run(repository.save(job.job_id, candidate))
            repeated_paths = asyncio.run(repository.save(job.job_id, candidate))
            restored = asyncio.run(repository.load(job.job_id))
            self.assertEqual(
                paths,
                ("derived/assembled-draft.md", "control/final-validation.json"),
            )
            self.assertEqual(repeated_paths, paths)
            self.assertEqual(restored, candidate)

    def test_rejects_different_candidate_for_existing_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            artifacts = FilesystemJobArtifactRepository(root / "var")
            job = DocumentJob("job-" + "c" * 32)
            asyncio.run(
                artifacts.initialize(
                    job,
                    CreateDocumentJobDto(
                        str(root), "문서 작성", "output.md", "d" * 64
                    ),
                )
            )
            repository = FilesystemFinalDocumentRepository(artifacts)
            asyncio.run(repository.save(job.job_id, _candidate("# 첫 문서\n")))
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.save(job.job_id, _candidate("# 다른 문서\n")))
            self.assertEqual(captured.exception.code, "FINAL_ARTIFACT_INVALID")


if __name__ == "__main__":
    unittest.main()
