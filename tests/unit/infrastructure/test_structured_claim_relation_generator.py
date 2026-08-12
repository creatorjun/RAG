from __future__ import annotations

import asyncio
import json
import unittest

from enterprise_rag.application.dto.claims import ClaimDraftDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto, EvidenceItemDto
from enterprise_rag.domain.claims import ClaimKind, ClaimRelationType
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.infrastructure.models.structured_claim_relation_generator import (
    StructuredClaimRelationGenerator,
)


class _TextGenerator:
    model_id = "fake/model"
    model_revision = "a" * 40

    def __init__(self, response: str) -> None:
        self.response = response

    async def prepare(self) -> None:
        return None

    async def generate(self, system_prompt, user_prompt, max_output_tokens):
        return self.response


class _SequenceTextGenerator(_TextGenerator):
    def __init__(self, responses: list[str]) -> None:
        super().__init__(responses[-1])
        self.responses = iter(responses)
        self.prompts: list[str] = []

    async def generate(self, system_prompt, user_prompt, max_output_tokens):
        self.prompts.append(user_prompt)
        return next(self.responses)


def _fixture() -> tuple[tuple[ClaimDraftDto, ...], EvidenceBundleDto]:
    evidence_items = tuple(
        EvidenceItemDto(
            "evidence:sha256:" + character * 64,
            f"chunk:{character}",
            f"revision:{character}",
            f"{character}.md",
            character * 64,
            0,
            0,
            4,
            chr(ord(character) + 2) * 64,
            "text",
        )
        for character in ("a", "b")
    )
    evidence = EvidenceBundleDto(evidence_items, 2, 2)
    drafts = (
        ClaimDraftDto(
            "draft:one",
            ClaimKind.FACT,
            "포트는 8080이다.",
            (evidence_items[0].evidence_id,),
        ),
        ClaimDraftDto(
            "draft:two",
            ClaimKind.FACT,
            "서비스 포트는 9090이다.",
            (evidence_items[1].evidence_id,),
        ),
    )
    return drafts, evidence


class StructuredClaimRelationGeneratorTest(unittest.TestCase):
    def test_rejects_unsafe_output_budget_and_skips_single_claim_comparison(self) -> None:
        drafts, evidence = _fixture()
        with self.assertRaises(ValueError):
            StructuredClaimRelationGenerator(_TextGenerator("{}"), 511)
        generator = StructuredClaimRelationGenerator(_TextGenerator("{}"), 512)
        self.assertEqual(
            asyncio.run(generator.generate(drafts[:1], evidence, "문서 작성")),
            (),
        )

    def test_parses_meaningful_relation_between_known_claims(self) -> None:
        drafts, evidence = _fixture()
        response = json.dumps(
            {
                "relations": [
                    {
                        "left_draft_id": "draft:one",
                        "right_draft_id": "draft:two",
                        "relation": "CONFLICT",
                    }
                ],
                "completion_marker": "RELATIONS_COMPLETE",
            }
        )
        generator = StructuredClaimRelationGenerator(_TextGenerator(response), 1024)
        relations = asyncio.run(
            generator.generate(drafts, evidence, "서비스 운영 문서")
        )
        self.assertEqual(relations[0].relation, ClaimRelationType.CONFLICT)

    def test_rejects_unknown_claim_or_unrelated_output(self) -> None:
        drafts, evidence = _fixture()
        response = json.dumps(
            {
                "relations": [
                    {
                        "left_draft_id": "draft:one",
                        "right_draft_id": "draft:unknown",
                        "relation": "UNRELATED",
                    }
                ],
                "completion_marker": "RELATIONS_COMPLETE",
            }
        )
        generator = StructuredClaimRelationGenerator(_TextGenerator(response), 1024)
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(generator.generate(drafts, evidence, "서비스 운영 문서"))
        self.assertEqual(captured.exception.code, "CLAIM_LEDGER_INVALID")

    def test_repairs_invalid_relation_output_once(self) -> None:
        drafts, evidence = _fixture()
        valid = json.dumps(
            {"relations": [], "completion_marker": "RELATIONS_COMPLETE"}
        )
        text_generator = _SequenceTextGenerator(["not-json", valid])

        relations = asyncio.run(
            StructuredClaimRelationGenerator(text_generator, 1024).generate(
                drafts, evidence, "서비스 운영 문서"
            )
        )

        self.assertEqual(relations, ())
        self.assertEqual(len(text_generator.prompts), 2)
        self.assertIn("validation_feedback", text_generator.prompts[1])


if __name__ == "__main__":
    unittest.main()
