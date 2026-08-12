from __future__ import annotations

import asyncio
import json
import unittest

from enterprise_rag.application.dto.claims import ClaimDto, ClaimLedgerDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto, EvidenceItemDto
from enterprise_rag.domain.claims import ClaimKind
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.infrastructure.models.structured_task_definition_generator import (
    StructuredTaskDefinitionGenerator,
)


class _TextGenerator:
    model_id = "fake/model"
    model_revision = "a" * 40

    def __init__(self, response: str) -> None:
        self.response = response
        self.user_prompt = ""

    async def prepare(self) -> None:
        return None

    async def generate(self, system_prompt, user_prompt, max_output_tokens):
        self.user_prompt = user_prompt
        return self.response


def _fixture() -> tuple[ClaimLedgerDto, EvidenceBundleDto]:
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
    return ledger, evidence


class StructuredTaskDefinitionGeneratorTest(unittest.TestCase):
    def test_rejects_unsafe_output_budget(self) -> None:
        with self.assertRaises(ValueError):
            StructuredTaskDefinitionGenerator(_TextGenerator("{}"), 511)

    def test_parses_task_boundaries_without_receiving_evidence_body(self) -> None:
        ledger, evidence = _fixture()
        response = json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "service-overview",
                        "title": "서비스 개요",
                        "objective": "서비스 사실 작성",
                        "owned_claim_ids": [ledger.claims[0].claim_id],
                        "required_sections": ["개요"],
                        "depends_on_task_ids": [],
                    }
                ],
                "completion_marker": "TASK_PLAN_COMPLETE",
            },
            ensure_ascii=False,
        )
        text_generator = _TextGenerator(response)
        definitions = asyncio.run(
            StructuredTaskDefinitionGenerator(text_generator, 1024).generate(
                ledger,
                evidence,
                "통합 문서 작성",
            )
        )
        self.assertEqual(definitions[0].task_id, "service-overview")
        self.assertIn("guide.md", text_generator.user_prompt)
        self.assertNotIn('"text": "text"', text_generator.user_prompt)

    def test_rejects_non_ascii_task_id_and_incomplete_marker(self) -> None:
        ledger, evidence = _fixture()
        response = json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "서비스-개요",
                        "title": "서비스 개요",
                        "objective": "서비스 사실 작성",
                        "owned_claim_ids": [ledger.claims[0].claim_id],
                        "required_sections": ["개요"],
                        "depends_on_task_ids": [],
                    }
                ],
                "completion_marker": "TRUNCATED",
            },
            ensure_ascii=False,
        )
        generator = StructuredTaskDefinitionGenerator(_TextGenerator(response), 1024)
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(generator.generate(ledger, evidence, "통합 문서 작성"))
        self.assertEqual(captured.exception.code, "TASK_PLAN_INVALID")


if __name__ == "__main__":
    unittest.main()
