from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from enterprise_rag.application.dto.jobs import CreateDocumentJobDto
from enterprise_rag.application.dto.tasks import (
    ClaimCoverageDto,
    CoverageMatrixDto,
    EvidenceCoverageDto,
    TaskPacketDto,
    TaskPlanDto,
)
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.jobs.filesystem_job_artifact_repository import (
    FilesystemJobArtifactRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_task_plan_repository import (
    FilesystemTaskPlanRepository,
)


class FilesystemTaskPlanRepositoryTest(unittest.TestCase):
    def test_round_trips_fixed_task_packets_and_coverage_matrix(self) -> None:
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
            claim_id = "claim:sha256:" + "c" * 64
            evidence_id = "evidence:sha256:" + "d" * 64
            packet = TaskPacketDto(
                task_id="security-task",
                title="보안",
                objective="보안 절차 작성",
                owned_claim_ids=(claim_id,),
                context_claim_ids=(),
                allowed_evidence_ids=(evidence_id,),
                relations=(),
                required_sections=("전제조건", "검증"),
                depends_on_task_ids=(),
            )
            coverage = CoverageMatrixDto(
                claim_coverage=(ClaimCoverageDto(claim_id, packet.task_id),),
                evidence_coverage=(EvidenceCoverageDto(evidence_id, (packet.task_id,)),),
                source_claim_count=1,
                source_evidence_count=1,
            )
            plan = TaskPlanDto((packet,), coverage)
            repository = FilesystemTaskPlanRepository(artifacts)
            path = asyncio.run(repository.save(job.job_id, plan))
            restored = asyncio.run(repository.load(job.job_id))
            self.assertEqual(path, "control/task-plan.json")
            self.assertEqual(restored, plan)
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.save(job.job_id, plan))
            self.assertEqual(captured.exception.code, "JOB_ARTIFACT_ALREADY_EXISTS")


if __name__ == "__main__":
    unittest.main()
