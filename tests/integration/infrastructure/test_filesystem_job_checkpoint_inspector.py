from __future__ import annotations

import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path

from enterprise_rag.application.dto.claims import ClaimDraftDto, ClaimDto, ClaimLedgerDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto, EvidenceItemDto
from enterprise_rag.application.dto.job_dashboard import CheckpointStatus
from enterprise_rag.application.dto.jobs import CreateDocumentJobDto
from enterprise_rag.application.dto.tasks import (
    ClaimCoverageDto,
    CoverageMatrixDto,
    EvidenceCoverageDto,
    FinalDocumentCandidateDto,
    FinalQualityReportDto,
    TaskOutputDto,
    TaskPacketDto,
    TaskPlanDto,
    TaskSectionOutputDto,
    TaskValidationReportDto,
)
from enterprise_rag.domain.claims import ClaimKind
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.jobs.filesystem_claim_draft_repository import (
    FilesystemClaimDraftRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_claim_ledger_repository import (
    FilesystemClaimLedgerRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_evidence_repository import (
    FilesystemEvidenceRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_final_document_repository import (
    FilesystemFinalDocumentRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_job_artifact_repository import (
    FilesystemJobArtifactRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_job_checkpoint_inspector import (
    FilesystemJobCheckpointInspector,
)
from enterprise_rag.infrastructure.jobs.filesystem_task_plan_repository import (
    FilesystemTaskPlanRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_task_result_repository import (
    FilesystemTaskResultRepository,
)


class FilesystemJobCheckpointInspectorTest(unittest.TestCase):
    def test_treats_legacy_validation_failures_as_saved_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            artifacts = FilesystemJobArtifactRepository(root / "var")
            plans = FilesystemTaskPlanRepository(artifacts)
            results = FilesystemTaskResultRepository(artifacts)
            inspector = FilesystemJobCheckpointInspector(
                artifacts,
                FilesystemEvidenceRepository(artifacts),
                FilesystemClaimLedgerRepository(artifacts),
                plans,
                results,
                FilesystemFinalDocumentRepository(artifacts),
            )
            job = DocumentJob("job-" + "a" * 32)
            asyncio.run(
                artifacts.initialize(
                    job,
                    CreateDocumentJobDto(str(root), "문서 작성", "out.md", "b" * 64),
                )
            )
            evidence_id = "evidence:sha256:" + "c" * 64
            claim_id = "claim:sha256:" + "d" * 64
            packet = TaskPacketDto(
                "failing-task",
                "실패 Task",
                "실패 진단",
                (claim_id,),
                (),
                (evidence_id,),
                (),
                ("개요",),
                (),
            )
            plan = TaskPlanDto(
                (packet,),
                CoverageMatrixDto(
                    (ClaimCoverageDto(claim_id, packet.task_id),),
                    (EvidenceCoverageDto(evidence_id, (packet.task_id,)),),
                    1,
                    1,
                ),
            )
            output = TaskOutputDto(
                packet.task_id,
                (
                    TaskSectionOutputDto(
                        "개요",
                        "개요",
                        f"본문 [evidence:{evidence_id}]",
                        (claim_id,),
                        (evidence_id,),
                    ),
                ),
                (),
                "TASK_COMPLETE",
            )
            asyncio.run(plans.save(job.job_id, plan))
            for attempt in range(1, 4):
                asyncio.run(results.save_output(job.job_id, attempt, output))
                asyncio.run(
                    results.save_validation(
                        job.job_id,
                        attempt,
                        TaskValidationReportDto(
                            packet.task_id,
                            False,
                            ("OWNED_CLAIM_MISSING",),
                        ),
                    )
                )

            checkpoint = asyncio.run(inspector._task_attempts_checkpoint(job.job_id))

            self.assertEqual(checkpoint.status, CheckpointStatus.SAVED)
            self.assertEqual(checkpoint.item_count, 1)
            self.assertTrue(checkpoint.resumable)
            self.assertIn("Task 출력 1/1건", checkpoint.detail)
            self.assertNotIn("OWNED_CLAIM_MISSING", checkpoint.detail)

    def test_reports_verified_checkpoint_counts_and_missing_source_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            artifacts = FilesystemJobArtifactRepository(root / "var")
            evidence_repository = FilesystemEvidenceRepository(artifacts)
            claim_repository = FilesystemClaimLedgerRepository(artifacts)
            claim_draft_repository = FilesystemClaimDraftRepository(artifacts)
            plan_repository = FilesystemTaskPlanRepository(artifacts)
            result_repository = FilesystemTaskResultRepository(artifacts)
            final_repository = FilesystemFinalDocumentRepository(artifacts)
            inspector = FilesystemJobCheckpointInspector(
                artifacts,
                evidence_repository,
                claim_repository,
                plan_repository,
                result_repository,
                final_repository,
                claim_draft_repository,
            )
            job = DocumentJob("job-" + "a" * 32)
            asyncio.run(
                artifacts.initialize(
                    job,
                    CreateDocumentJobDto(str(root), "문서 작성", "out.md", "b" * 64),
                )
            )
            initial = {
                item.checkpoint_id: item
                for item in asyncio.run(inspector.inspect(job.job_id))
            }
            self.assertEqual(initial["definition"].status, CheckpointStatus.SAVED)
            self.assertEqual(initial["source_manifest"].status, CheckpointStatus.MISSING)
            self.assertEqual(initial["evidence"].status, CheckpointStatus.MISSING)

            evidence_id = "evidence:sha256:" + "c" * 64
            claim_id = "claim:sha256:" + "d" * 64
            evidence = EvidenceBundleDto(
                (
                    EvidenceItemDto(
                        evidence_id,
                        "chunk:1",
                        "revision:1",
                        "guide.md",
                        "e" * 64,
                        0,
                        0,
                        4,
                        "f" * 64,
                        "text",
                    ),
                ),
                1,
                1,
            )
            ledger = ClaimLedgerDto(
                (ClaimDto(claim_id, ClaimKind.FACT, "사실", (evidence_id,)),),
                (),
                (evidence_id,),
            )
            packet = TaskPacketDto(
                "service-task",
                "서비스",
                "서비스 작성",
                (claim_id,),
                (),
                (evidence_id,),
                (),
                ("개요",),
                (),
            )
            plan = TaskPlanDto(
                (packet,),
                CoverageMatrixDto(
                    (ClaimCoverageDto(claim_id, packet.task_id),),
                    (EvidenceCoverageDto(evidence_id, (packet.task_id,)),),
                    1,
                    1,
                ),
            )
            output = TaskOutputDto(
                packet.task_id,
                (
                    TaskSectionOutputDto(
                        "개요",
                        "개요",
                        f"사실 [evidence:{evidence_id}]",
                        (claim_id,),
                        (evidence_id,),
                    ),
                ),
                (),
                "TASK_COMPLETE",
            )
            validation = TaskValidationReportDto(packet.task_id, True, ())
            markdown = (
                "# 문서\n\n## 서비스\n\n### 개요\n\n"
                "사실 [source:guide.md]\n\n## 원본 문서 목록\n\n- `guide.md`\n"
            )
            quality = FinalQualityReportDto(
                True,
                (),
                hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
                1,
                1,
                1,
                1,
                1,
                1,
                1,
            )
            asyncio.run(evidence_repository.save(job.job_id, evidence))
            asyncio.run(
                claim_draft_repository.save(
                    job.job_id,
                    evidence_id,
                    (
                        ClaimDraftDto(
                            "draft:chunk:1",
                            ClaimKind.FACT,
                            "사실",
                            (evidence_id,),
                        ),
                    ),
                )
            )
            asyncio.run(claim_repository.save(job.job_id, ledger))
            asyncio.run(plan_repository.save(job.job_id, plan))
            asyncio.run(result_repository.save_output(job.job_id, 1, output))
            asyncio.run(result_repository.save_validation(job.job_id, 1, validation))
            asyncio.run(
                final_repository.save(
                    job.job_id,
                    FinalDocumentCandidateDto(markdown, quality),
                )
            )

            checkpoints = {
                item.checkpoint_id: item
                for item in asyncio.run(inspector.inspect(job.job_id))
            }
            for checkpoint_id in (
                "evidence",
                "claim_drafts",
                "claim_ledger",
                "task_plan",
                "task_attempts",
                "assembled_draft",
                "final_quality",
            ):
                self.assertEqual(
                    checkpoints[checkpoint_id].status,
                    CheckpointStatus.SAVED,
                    checkpoint_id,
                )
            self.assertEqual(checkpoints["task_attempts"].item_count, 1)

    def test_distinguishes_missing_and_corrupt_final_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            artifacts = FilesystemJobArtifactRepository(root / "var")
            inspector = FilesystemJobCheckpointInspector(
                artifacts,
                FilesystemEvidenceRepository(artifacts),
                FilesystemClaimLedgerRepository(artifacts),
                FilesystemTaskPlanRepository(artifacts),
                FilesystemTaskResultRepository(artifacts),
                FilesystemFinalDocumentRepository(artifacts),
            )
            job = DocumentJob("job-" + "a" * 32)
            asyncio.run(
                artifacts.initialize(
                    job,
                    CreateDocumentJobDto(str(root), "문서 작성", "out.md", "b" * 64),
                )
            )

            missing = {
                item.checkpoint_id: item
                for item in asyncio.run(inspector.inspect(job.job_id))
            }
            self.assertEqual(missing["final_quality"].status, CheckpointStatus.MISSING)

            asyncio.run(
                artifacts.write_json_once(
                    job.job_id,
                    "control/final-validation.json",
                    {"schema_version": 999, "job_id": job.job_id},
                )
            )
            corrupt = {
                item.checkpoint_id: item
                for item in asyncio.run(inspector.inspect(job.job_id))
            }
            self.assertEqual(corrupt["final_quality"].status, CheckpointStatus.INVALID)

    def test_reports_missing_checkpoints_when_job_artifact_directory_is_lost(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            artifacts = FilesystemJobArtifactRepository(root / "var")
            inspector = FilesystemJobCheckpointInspector(
                artifacts,
                FilesystemEvidenceRepository(artifacts),
                FilesystemClaimLedgerRepository(artifacts),
                FilesystemTaskPlanRepository(artifacts),
                FilesystemTaskResultRepository(artifacts),
                FilesystemFinalDocumentRepository(artifacts),
            )
            job = DocumentJob("job-" + "a" * 32)
            asyncio.run(
                artifacts.initialize(
                    job,
                    CreateDocumentJobDto(str(root), "문서 작성", "out.md", "b" * 64),
                )
            )
            (root / "var/jobs" / job.job_id).rename(root / "detached-job")

            checkpoints = {
                item.checkpoint_id: item
                for item in asyncio.run(inspector.inspect(job.job_id))
            }
            self.assertEqual(checkpoints["definition"].status, CheckpointStatus.MISSING)
            self.assertEqual(checkpoints["task_attempts"].status, CheckpointStatus.MISSING)


if __name__ == "__main__":
    unittest.main()
