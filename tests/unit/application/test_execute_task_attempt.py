from __future__ import annotations

import asyncio
import unittest

from enterprise_rag.application.dto.claims import ClaimDto, ClaimLedgerDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto, EvidenceItemDto
from enterprise_rag.application.dto.tasks import (
    TaskOutputDto,
    TaskPacketDto,
    TaskSectionOutputDto,
    TaskValidationReportDto,
)
from enterprise_rag.application.use_cases.execute_task_attempt import ExecuteTaskAttempt
from enterprise_rag.application.use_cases.validate_task_output import ValidateTaskOutput
from enterprise_rag.domain.claims import ClaimKind
from enterprise_rag.domain.errors import ApplicationError


def _fixture() -> tuple[EvidenceBundleDto, ClaimLedgerDto, TaskPacketDto]:
    evidence_id = "evidence:sha256:" + "a" * 64
    claim_id = "claim:sha256:" + "b" * 64
    evidence_item = EvidenceItemDto(
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
    )
    evidence = EvidenceBundleDto((evidence_item,), 1, 1)
    claim = ClaimDto(
        claim_id,
        ClaimKind.PROCEDURE,
        "서비스를 시작한다.",
        (evidence_id,),
    )
    ledger = ClaimLedgerDto((claim,), (), (evidence_id,))
    packet = TaskPacketDto(
        "service-task",
        "서비스 운영",
        "서비스 절차 작성",
        (claim_id,),
        (),
        (evidence_id,),
        (),
        ("절차",),
        (),
    )
    return evidence, ledger, packet


class _Generator:
    def __init__(self, output: TaskOutputDto) -> None:
        self.output = output
        self.received_claim_count = 0
        self.received_evidence_count = 0

    async def generate(self, packet, claims, evidence, previous_validation=None):
        self.received_claim_count = len(claims)
        self.received_evidence_count = len(evidence)
        return self.output


class _Results:
    def __init__(self) -> None:
        self.output: TaskOutputDto | None = None
        self.validation: TaskValidationReportDto | None = None

    async def save_output(self, job_id, attempt, output):
        self.output = output
        return "output.json"

    async def load_output(self, job_id, task_id, attempt):
        if self.output is None:
            raise AssertionError("output not saved")
        return self.output

    async def save_validation(self, job_id, attempt, report):
        self.validation = report
        return "validation.json"

    async def load_validation(self, job_id, task_id, attempt):
        if self.validation is None:
            raise AssertionError("validation not saved")
        return self.validation


class ExecuteTaskAttemptTest(unittest.TestCase):
    def test_generates_persists_and_validates_one_bounded_attempt(self) -> None:
        evidence, ledger, packet = _fixture()
        evidence_id = packet.allowed_evidence_ids[0]
        output = TaskOutputDto(
            packet.task_id,
            (
                TaskSectionOutputDto(
                    "절차",
                    "표준 절차",
                    f"서비스를 시작한다. [evidence:{evidence_id}]",
                    packet.owned_claim_ids,
                    (evidence_id,),
                ),
            ),
            (),
            "TASK_COMPLETE",
        )
        generator = _Generator(output)
        results = _Results()
        use_case = ExecuteTaskAttempt(generator, results, ValidateTaskOutput())
        result = asyncio.run(
            use_case.execute(
                "job-" + "a" * 32,
                packet,
                ledger,
                evidence,
                1,
            )
        )
        self.assertTrue(result.validation.valid)
        self.assertEqual(results.output, output)
        self.assertEqual(results.validation, result.validation)
        self.assertEqual(generator.received_claim_count, 1)
        self.assertEqual(generator.received_evidence_count, 1)

    def test_rejects_retry_without_prior_invalid_validation(self) -> None:
        evidence, ledger, packet = _fixture()
        evidence_id = packet.allowed_evidence_ids[0]
        output = TaskOutputDto(
            packet.task_id,
            (
                TaskSectionOutputDto(
                    "절차",
                    "표준 절차",
                    f"본문 [evidence:{evidence_id}]",
                    packet.owned_claim_ids,
                    (evidence_id,),
                ),
            ),
            (),
            "TASK_COMPLETE",
        )
        use_case = ExecuteTaskAttempt(_Generator(output), _Results(), ValidateTaskOutput())
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(
                use_case.execute(
                    "job-" + "a" * 32,
                    packet,
                    ledger,
                    evidence,
                    2,
                )
            )
        self.assertEqual(captured.exception.code, "TASK_OUTPUT_INVALID")


if __name__ == "__main__":
    unittest.main()
