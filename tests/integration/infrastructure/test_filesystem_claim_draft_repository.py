from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from enterprise_rag.application.dto.claims import ClaimDraftDto
from enterprise_rag.application.dto.jobs import CreateDocumentJobDto
from enterprise_rag.domain.claims import ClaimKind
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.jobs.filesystem_claim_draft_repository import (
    FilesystemClaimDraftRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_job_artifact_repository import (
    FilesystemJobArtifactRepository,
)


class FilesystemClaimDraftRepositoryTest(unittest.TestCase):
    def test_round_trips_valid_and_empty_evidence_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts = FilesystemJobArtifactRepository(root / "var")
            repository = FilesystemClaimDraftRepository(artifacts)
            job = DocumentJob("job-" + "a" * 32)
            asyncio.run(
                artifacts.initialize(
                    job,
                    CreateDocumentJobDto(str(root), "작성", "out.md", "b" * 64),
                )
            )
            relevant_id = "evidence:sha256:" + "c" * 64
            irrelevant_id = "evidence:sha256:" + "d" * 64
            draft = ClaimDraftDto(
                "draft:one",
                ClaimKind.PROCEDURE,
                "절차",
                (relevant_id,),
                ("조건",),
                ("명령",),
                ("주의",),
            )

            asyncio.run(repository.save(job.job_id, relevant_id, (draft,)))
            asyncio.run(repository.save(job.job_id, irrelevant_id, ()))

            self.assertEqual(
                asyncio.run(repository.load(job.job_id, relevant_id)),
                (draft,),
            )
            self.assertEqual(
                asyncio.run(repository.load(job.job_id, irrelevant_id)),
                (),
            )
            self.assertIsNone(
                asyncio.run(
                    repository.load(job.job_id, "evidence:sha256:" + "e" * 64)
                )
            )

    def test_rejects_invalid_evidence_identity_and_cross_evidence_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts = FilesystemJobArtifactRepository(root / "var")
            repository = FilesystemClaimDraftRepository(artifacts)
            job = DocumentJob("job-" + "f" * 32)
            asyncio.run(
                artifacts.initialize(
                    job,
                    CreateDocumentJobDto(str(root), "작성", "out.md", "1" * 64),
                )
            )
            evidence_id = "evidence:sha256:" + "2" * 64
            wrong = ClaimDraftDto(
                "draft:wrong",
                ClaimKind.FACT,
                "사실",
                ("evidence:sha256:" + "3" * 64,),
            )
            for invalid_id, drafts in (("bad", ()), (evidence_id, (wrong,))):
                with self.subTest(invalid_id=invalid_id), self.assertRaises(
                    ApplicationError
                ) as captured:
                    asyncio.run(repository.save(job.job_id, invalid_id, drafts))
                self.assertEqual(captured.exception.code, "CLAIM_LEDGER_INVALID")


if __name__ == "__main__":
    unittest.main()
