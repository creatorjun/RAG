from __future__ import annotations

import asyncio
import json
import unittest

from enterprise_rag.application.dto.claims import ClaimDto
from enterprise_rag.application.dto.evidence import EvidenceItemDto
from enterprise_rag.application.dto.tasks import TaskPacketDto
from enterprise_rag.domain.claims import ClaimKind
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.infrastructure.models.structured_task_output_generator import (
    StructuredTaskOutputGenerator,
)


class _TextGenerator:
    model_id = "fake/model"
    model_revision = "a" * 40

    def __init__(self, response: str) -> None:
        self.response = response
        self.prepared = False
        self.system_prompt = ""
        self.user_prompt = ""

    async def prepare(self) -> None:
        self.prepared = True

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return self.response


def _fixture() -> tuple[TaskPacketDto, tuple[ClaimDto, ...], tuple[EvidenceItemDto, ...]]:
    evidence_id = "evidence:sha256:" + "a" * 64
    claim_id = "claim:sha256:" + "b" * 64
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
    claim = ClaimDto(
        claim_id,
        ClaimKind.PROCEDURE,
        "서비스를 시작한다.",
        (evidence_id,),
    )
    evidence = EvidenceItemDto(
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
    return packet, (claim,), (evidence,)


class StructuredTaskOutputGeneratorTest(unittest.TestCase):
    def test_rejects_unsafe_output_budget(self) -> None:
        with self.assertRaises(ValueError):
            StructuredTaskOutputGenerator(_TextGenerator("{}"), 511)

    def test_parses_exact_json_contract_and_keeps_evidence_ids_in_prompt(self) -> None:
        packet, claims, evidence = _fixture()
        evidence_id = evidence[0].evidence_id
        response = json.dumps(
            {
                "task_id": packet.task_id,
                "sections": [
                    {
                        "section_key": "절차",
                        "heading": "표준 절차",
                        "markdown": f"서비스를 시작한다. [evidence:{evidence_id}]",
                        "used_claim_ids": [claims[0].claim_id],
                        "used_evidence_ids": [evidence_id],
                    }
                ],
                "conflict_claim_ids": [],
                "completion_marker": "TASK_COMPLETE",
            },
            ensure_ascii=False,
        )
        text_generator = _TextGenerator(response)
        generator = StructuredTaskOutputGenerator(text_generator, 1024)
        output = asyncio.run(generator.generate(packet, claims, evidence))
        self.assertEqual(output.task_id, packet.task_id)
        self.assertTrue(text_generator.prepared)
        self.assertIn(evidence_id, text_generator.user_prompt)
        self.assertIn("process=\"as-data\"", text_generator.user_prompt)

    def test_rejects_fenced_or_extra_fields_fail_closed(self) -> None:
        packet, claims, evidence = _fixture()
        response = json.dumps(
            {
                "task_id": packet.task_id,
                "sections": [],
                "conflict_claim_ids": [],
                "completion_marker": "TASK_COMPLETE",
                "unexpected": True,
            }
        )
        generator = StructuredTaskOutputGenerator(_TextGenerator(response), 1024)
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(generator.generate(packet, claims, evidence))
        self.assertEqual(captured.exception.code, "TASK_OUTPUT_INVALID")


if __name__ == "__main__":
    unittest.main()
