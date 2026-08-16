from __future__ import annotations

import unittest

from enterprise_rag.application.dto.claims import (
    ClaimDto,
    ClaimLedgerDto,
    ClaimRelationDto,
)
from enterprise_rag.application.dto.tasks import TaskDefinitionDto
from enterprise_rag.application.use_cases.build_task_plan import BuildTaskPlan
from enterprise_rag.domain.claims import ClaimKind, ClaimRelationType
from enterprise_rag.domain.errors import ApplicationError


def _ledger(extra_unclaimed_evidence: bool = False) -> ClaimLedgerDto:
    first_evidence = "evidence:sha256:" + "a" * 64
    second_evidence = "evidence:sha256:" + "b" * 64
    first = ClaimDto(
        "claim:sha256:" + "c" * 64,
        ClaimKind.PROCEDURE,
        "서비스를 시작한다.",
        (first_evidence,),
    )
    second = ClaimDto(
        "claim:sha256:" + "d" * 64,
        ClaimKind.VALIDATION,
        "서비스를 검증한다.",
        (second_evidence,),
    )
    relation = ClaimRelationDto(
        first.claim_id,
        second.claim_id,
        ClaimRelationType.COMPLEMENTARY,
    )
    evidence = [first_evidence, second_evidence]
    if extra_unclaimed_evidence:
        evidence.append("evidence:sha256:" + "e" * 64)
    return ClaimLedgerDto((first, second), (relation,), tuple(evidence))


class BuildTaskPlanTest(unittest.TestCase):
    def test_consolidates_identical_topics_from_independent_plan_batches(self) -> None:
        ledger = _ledger()
        definitions = (
            TaskDefinitionDto(
                "batch-one-service",
                "## 서비스 운영",
                "서비스 시작 범위",
                (ledger.claims[0].claim_id,),
                ("시작",),
            ),
            TaskDefinitionDto(
                "batch-two-service",
                "서비스 운영",
                "서비스 시작 후 검증 범위",
                (ledger.claims[1].claim_id,),
                ("검증",),
                ("batch-one-service",),
            ),
        )

        plan = BuildTaskPlan().execute(ledger, definitions)

        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.tasks[0].title, "서비스 운영")
        self.assertEqual(
            set(plan.tasks[0].owned_claim_ids),
            {item.claim_id for item in ledger.claims},
        )
        self.assertEqual(plan.tasks[0].required_sections, ("시작", "검증"))
        self.assertEqual(plan.tasks[0].depends_on_task_ids, ())

    def test_assigns_every_claim_once_and_adds_cross_task_relation_context(self) -> None:
        ledger = _ledger()
        definitions = (
            TaskDefinitionDto(
                "service-task",
                "서비스 운영",
                "서비스를 시작한다.",
                (ledger.claims[0].claim_id,),
                ("전제조건", "절차"),
            ),
            TaskDefinitionDto(
                "validation-task",
                "서비스 검증",
                "서비스 결과를 검증한다.",
                (ledger.claims[1].claim_id,),
                ("검증",),
                ("service-task",),
            ),
        )
        plan = BuildTaskPlan().execute(ledger, definitions)
        self.assertEqual(len(plan.tasks), 2)
        self.assertEqual(plan.coverage.source_claim_count, 2)
        self.assertEqual(plan.coverage.source_evidence_count, 2)
        self.assertEqual(
            plan.tasks[0].context_claim_ids,
            (ledger.claims[1].claim_id,),
        )
        self.assertEqual(len(plan.tasks[0].allowed_evidence_ids), 2)

    def test_rejects_missing_or_duplicate_claim_owner(self) -> None:
        ledger = _ledger()
        missing = (
            TaskDefinitionDto(
                "only-task",
                "일부",
                "일부만 작성",
                (ledger.claims[0].claim_id,),
                ("절차",),
            ),
        )
        with self.assertRaises(ApplicationError) as captured:
            BuildTaskPlan().execute(ledger, missing)
        self.assertEqual(captured.exception.code, "COVERAGE_MATRIX_INCOMPLETE")

        duplicate = (
            missing[0],
            TaskDefinitionDto(
                "other-task",
                "중복",
                "같은 Claim 중복 소유",
                (ledger.claims[0].claim_id, ledger.claims[1].claim_id),
                ("검증",),
            ),
        )
        with self.assertRaises(ApplicationError) as captured:
            BuildTaskPlan().execute(ledger, duplicate)
        self.assertEqual(captured.exception.code, "COVERAGE_MATRIX_INCOMPLETE")

    def test_rejects_unclaimed_evidence_and_dependency_cycle(self) -> None:
        ledger = _ledger(extra_unclaimed_evidence=True)
        definition = TaskDefinitionDto(
            "all-task",
            "전체",
            "전체 Claim 작성",
            tuple(claim.claim_id for claim in ledger.claims),
            ("절차", "검증"),
        )
        with self.assertRaises(ApplicationError) as captured:
            BuildTaskPlan().execute(ledger, (definition,))
        self.assertEqual(captured.exception.code, "COVERAGE_MATRIX_INCOMPLETE")

        clean = _ledger()
        cyclic = (
            TaskDefinitionDto(
                "first-task",
                "첫째",
                "첫째",
                (clean.claims[0].claim_id,),
                ("절차",),
                ("second-task",),
            ),
            TaskDefinitionDto(
                "second-task",
                "둘째",
                "둘째",
                (clean.claims[1].claim_id,),
                ("검증",),
                ("first-task",),
            ),
        )
        with self.assertRaises(ApplicationError) as captured:
            BuildTaskPlan().execute(clean, cyclic)
        self.assertEqual(captured.exception.code, "TASK_PLAN_INVALID")


if __name__ == "__main__":
    unittest.main()
