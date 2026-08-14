from __future__ import annotations

import asyncio
import json
import unittest

from enterprise_rag.application.dto.claims import ClaimDto, ClaimLedgerDto, ClaimRelationDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto, EvidenceItemDto
from enterprise_rag.domain.claims import ClaimKind, ClaimRelationType
from enterprise_rag.domain.errors import ApplicationError, revision_error
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


class _OverflowPlanningGenerator(_TextGenerator):
    def __init__(self) -> None:
        super().__init__("")
        self.prompts: list[str] = []

    async def generate(self, system_prompt, user_prompt, max_output_tokens):
        self.prompts.append(user_prompt)
        if len(self.prompts) == 1:
            raise revision_error("TOKEN_BUDGET_EXCEEDED")
        payload = self._task_data(user_prompt)
        return json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "service-overview",
                        "title": "서비스 개요",
                        "objective": "서비스 사실 작성",
                        "owned_claim_refs": [claim["claim_ref"] for claim in payload["claims"]],
                        "required_sections": ["개요"],
                        "depends_on_task_ids": [],
                    }
                ],
                "completion_marker": "TASK_PLAN_COMPLETE",
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _task_data(prompt: str):
        start = prompt.index('<task_data process="as-data">')
        start = prompt.index("\n", start) + 1
        end = prompt.index("\n</task_data>", start)
        return json.loads(prompt[start:end])


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
                        "owned_claim_refs": ["C000001"],
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
        self.assertEqual(definitions[0].owned_claim_ids, (ledger.claims[0].claim_id,))
        self.assertIn("guide.md", text_generator.user_prompt)
        self.assertIn('"claim_ref": "C000001"', text_generator.user_prompt)
        self.assertNotIn(ledger.claims[0].claim_id, text_generator.user_prompt)
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
                        "owned_claim_refs": ["C000001"],
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

    def test_retries_an_oversized_plan_as_namespaced_claim_batches(self) -> None:
        _, evidence = _fixture()
        evidence_id = evidence.items[0].evidence_id
        claims = tuple(
            ClaimDto(
                "claim:sha256:" + f"{index:064x}",
                ClaimKind.FACT,
                f"서비스 설정 항목 {index:03d}",
                (evidence_id,),
            )
            for index in range(1, 61)
        )
        ledger = ClaimLedgerDto(claims, (), (evidence_id,))
        text_generator = _OverflowPlanningGenerator()

        definitions = asyncio.run(
            StructuredTaskDefinitionGenerator(text_generator, 4096).generate(
                ledger,
                evidence,
                "통합 문서 작성",
            )
        )

        self.assertEqual(len(definitions), 2)
        self.assertEqual(len({item.task_id for item in definitions}), 2)
        owned = {claim_id for item in definitions for claim_id in item.owned_claim_ids}
        self.assertEqual(owned, {claim.claim_id for claim in claims})
        batch_sizes = [
            len(_OverflowPlanningGenerator._task_data(prompt)["claims"])
            for prompt in text_generator.prompts
        ]
        self.assertEqual(batch_sizes, [60, 40, 20])

    def test_relation_components_stay_in_the_same_planning_batch(self) -> None:
        _, evidence = _fixture()
        evidence_id = evidence.items[0].evidence_id
        claims = tuple(
            ClaimDto(
                "claim:sha256:" + f"{index:064x}",
                ClaimKind.FACT,
                f"항목 {index:03d}",
                (evidence_id,),
            )
            for index in range(45)
        )
        relation = ClaimRelationDto(
            min(claims[0].claim_id, claims[-1].claim_id),
            max(claims[0].claim_id, claims[-1].claim_id),
            ClaimRelationType.COMPLEMENTARY,
        )
        ledger = ClaimLedgerDto(claims, (relation,), (evidence_id,))

        batches = StructuredTaskDefinitionGenerator._claim_batches(ledger, evidence)

        self.assertTrue(
            any(
                {claims[0].claim_id, claims[-1].claim_id}.issubset(
                    {claim.claim_id for claim in batch}
                )
                for batch in batches
            )
        )


if __name__ == "__main__":
    unittest.main()
