from __future__ import annotations

import asyncio
import unittest

from enterprise_rag.application.dto.claims import ClaimDto, ClaimLedgerDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto, EvidenceItemDto
from enterprise_rag.application.dto.tasks import (
    ClaimCoverageDto,
    CoverageMatrixDto,
    EvidenceCoverageDto,
    TaskAttemptResultDto,
    TaskOutputDto,
    TaskPacketDto,
    TaskPlanDto,
    TaskSectionOutputDto,
    TaskValidationReportDto,
)
from enterprise_rag.application.use_cases.execute_task_plan import ExecuteTaskPlan
from enterprise_rag.domain.claims import ClaimKind


def _fixture() -> tuple[EvidenceBundleDto, ClaimLedgerDto, TaskPlanDto]:
    evidence_items = tuple(
        EvidenceItemDto(
            "evidence:sha256:" + character * 64,
            f"chunk:{index}",
            f"revision:{index}",
            f"guide-{index}.md",
            character * 64,
            0,
            0,
            4,
            chr(ord(character) + 2) * 64,
            "text",
        )
        for index, character in enumerate(("a", "b"), start=1)
    )
    evidence = EvidenceBundleDto(evidence_items, 2, 2)
    claims = tuple(
        ClaimDto(
            "claim:sha256:" + character * 64,
            ClaimKind.FACT,
            f"사실 {index}",
            (item.evidence_id,),
        )
        for index, (character, item) in enumerate(
            zip(("d", "e"), evidence_items, strict=True),
            start=1,
        )
    )
    ledger = ClaimLedgerDto(
        claims,
        (),
        tuple(item.evidence_id for item in evidence_items),
    )
    packets = tuple(
        TaskPacketDto(
            f"task-{index:02d}",
            f"태스크 {index}",
            f"태스크 {index} 작성",
            (claim.claim_id,),
            (),
            claim.evidence_ids,
            (),
            ("본문",),
            (() if index == 1 else ("task-01",)),
        )
        for index, claim in enumerate(claims, start=1)
    )
    coverage = CoverageMatrixDto(
        tuple(
            ClaimCoverageDto(claim.claim_id, packet.task_id)
            for claim, packet in zip(claims, packets, strict=True)
        ),
        tuple(
            EvidenceCoverageDto(item.evidence_id, (packet.task_id,))
            for item, packet in zip(evidence_items, packets, strict=True)
        ),
        2,
        2,
    )
    return evidence, ledger, TaskPlanDto(packets, coverage)


class _Attempts:
    def __init__(self, always_invalid: bool = False) -> None:
        self.always_invalid = always_invalid
        self.calls: list[tuple[str, int]] = []

    async def execute(
        self,
        job_id,
        packet,
        ledger,
        evidence,
        attempt,
        previous_validation=None,
    ):
        self.calls.append((packet.task_id, attempt))
        evidence_id = packet.allowed_evidence_ids[0]
        output = TaskOutputDto(
            packet.task_id,
            (
                TaskSectionOutputDto(
                    "본문",
                    "본문",
                    f"내용 [evidence:{evidence_id}]",
                    packet.owned_claim_ids,
                    (evidence_id,),
                ),
            ),
            (),
            "TASK_COMPLETE",
        )
        valid = not self.always_invalid and (packet.task_id != "task-01" or attempt > 1)
        report = TaskValidationReportDto(
            packet.task_id,
            valid,
            (() if valid else ("REWRITE_REQUIRED",)),
        )
        return TaskAttemptResultDto(attempt, output, report)


class ExecuteTaskPlanTest(unittest.TestCase):
    def test_rewrites_only_failed_task_then_continues_in_plan_order(self) -> None:
        evidence, ledger, plan = _fixture()
        attempts = _Attempts()
        progress = []
        result = asyncio.run(
            ExecuteTaskPlan(attempts).execute(
                "job-" + "a" * 32,
                plan,
                ledger,
                evidence,
                lambda completed, total, task_id, report: progress.append(
                    (completed, total, task_id, report.valid)
                ),
            )
        )
        self.assertTrue(result.complete)
        self.assertEqual(result.total_attempt_count, 3)
        self.assertEqual(
            attempts.calls,
            [("task-01", 1), ("task-01", 2), ("task-02", 1)],
        )
        self.assertEqual(progress[-1], (2, 2, "task-02", True))

    def test_stops_before_dependents_after_three_failed_attempts(self) -> None:
        evidence, ledger, plan = _fixture()
        attempts = _Attempts(always_invalid=True)
        result = asyncio.run(
            ExecuteTaskPlan(attempts).execute(
                "job-" + "b" * 32,
                plan,
                ledger,
                evidence,
            )
        )
        self.assertFalse(result.complete)
        self.assertEqual(result.total_attempt_count, 3)
        self.assertEqual(attempts.calls, [("task-01", 1), ("task-01", 2), ("task-01", 3)])
        self.assertEqual(len(result.outputs), 1)


if __name__ == "__main__":
    unittest.main()
