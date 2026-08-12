from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from enterprise_rag.application.dto.claims import ClaimDto, ClaimLedgerDto
from enterprise_rag.application.dto.jobs import CreateDocumentJobDto
from enterprise_rag.domain.claims import ClaimKind
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.jobs.filesystem_claim_ledger_repository import (
    FilesystemClaimLedgerRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_job_artifact_repository import (
    FilesystemJobArtifactRepository,
)


class FilesystemClaimLedgerRepositoryTest(unittest.TestCase):
    def test_round_trips_write_once_ledger_in_control_namespace(self) -> None:
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
            evidence_id = "evidence:sha256:" + "c" * 64
            claim = ClaimDto(
                claim_id="claim:sha256:" + "d" * 64,
                kind=ClaimKind.WARNING,
                statement="운영에서 직접 적용하지 않는다.",
                evidence_ids=(evidence_id,),
                warnings=("사람 승인이 필요하다.",),
            )
            ledger = ClaimLedgerDto((claim,), (), (evidence_id,))
            repository = FilesystemClaimLedgerRepository(artifacts)
            path = asyncio.run(repository.save(job.job_id, ledger))
            restored = asyncio.run(repository.load(job.job_id))
            self.assertEqual(path, "control/claim-ledger.json")
            self.assertEqual(restored, ledger)
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.save(job.job_id, ledger))
            self.assertEqual(captured.exception.code, "JOB_ARTIFACT_ALREADY_EXISTS")


if __name__ == "__main__":
    unittest.main()
