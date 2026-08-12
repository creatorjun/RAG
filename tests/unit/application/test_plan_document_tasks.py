from __future__ import annotations

import asyncio
import unittest

from enterprise_rag.application.dto.claims import ClaimDto, ClaimLedgerDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto, EvidenceItemDto
from enterprise_rag.application.dto.tasks import TaskDefinitionDto
from enterprise_rag.application.use_cases.build_task_plan import BuildTaskPlan
from enterprise_rag.application.use_cases.plan_document_tasks import PlanDocumentTasks
from enterprise_rag.domain.claims import ClaimKind
from enterprise_rag.domain.errors import ApplicationError


class _Generator:
    def __init__(self, definitions) -> None:
        self.definitions = definitions

    async def generate(self, ledger, evidence, instruction):
        return self.definitions


class PlanDocumentTasksTest(unittest.TestCase):
    def test_model_proposes_boundaries_but_code_enforces_full_coverage(self) -> None:
        evidence_id = "evidence:sha256:" + "a" * 64
        claim_id = "claim:sha256:" + "b" * 64
        evidence = EvidenceBundleDto(
            (
                EvidenceItemDto(
                    evidence_id,
                    "chunk:1",
                    "revision:1",
                    "guide.md",
                    "c" * 64,
                    0,
                    0,
                    4,
                    "d" * 64,
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
        definition = TaskDefinitionDto(
            "service-task",
            "서비스",
            "서비스 문서 작성",
            (claim_id,),
            ("개요",),
        )
        plan = asyncio.run(
            PlanDocumentTasks(_Generator((definition,)), BuildTaskPlan()).execute(
                ledger,
                evidence,
                "통합 문서 작성",
            )
        )
        self.assertEqual(plan.coverage.source_claim_count, 1)
        self.assertEqual(plan.coverage.source_evidence_count, 1)

        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(
                PlanDocumentTasks(_Generator(()), BuildTaskPlan()).execute(
                    ledger,
                    evidence,
                    "통합 문서 작성",
                )
            )
        self.assertEqual(captured.exception.code, "TASK_PLAN_INVALID")


if __name__ == "__main__":
    unittest.main()
