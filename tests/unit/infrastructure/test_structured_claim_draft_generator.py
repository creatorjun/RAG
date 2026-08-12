from __future__ import annotations

import asyncio
import json
import unittest

from enterprise_rag.application.dto.evidence import EvidenceItemDto
from enterprise_rag.domain.claims import ClaimKind
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.infrastructure.models.structured_claim_draft_generator import (
    StructuredClaimDraftGenerator,
)


class _TextGenerator:
    model_id = "fake/model"
    model_revision = "a" * 40

    def __init__(self, response: str) -> None:
        self.response = response
        self.prepared = False
        self.user_prompt = ""

    async def prepare(self) -> None:
        self.prepared = True

    async def generate(self, system_prompt, user_prompt, max_output_tokens):
        self.user_prompt = user_prompt
        return self.response


class _SequenceTextGenerator(_TextGenerator):
    def __init__(self, responses: list[str]) -> None:
        super().__init__(responses[-1])
        self.responses = iter(responses)
        self.prompts: list[str] = []

    async def generate(self, system_prompt, user_prompt, max_output_tokens):
        self.prompts.append(user_prompt)
        return next(self.responses)


def _evidence() -> EvidenceItemDto:
    return EvidenceItemDto(
        "evidence:sha256:" + "a" * 64,
        "chunk:1",
        "revision:1",
        "guide.md",
        "b" * 64,
        0,
        0,
        4,
        "c" * 64,
        "text",
    )


class StructuredClaimDraftGeneratorTest(unittest.TestCase):
    def test_rejects_unsafe_output_budget(self) -> None:
        with self.assertRaises(ValueError):
            StructuredClaimDraftGenerator(_TextGenerator("{}"), 511)

    def test_extracts_strict_claims_with_deterministic_draft_ids(self) -> None:
        evidence = _evidence()
        response = json.dumps(
            {
                "evidence_id": evidence.evidence_id,
                "claims": [
                    {
                        "kind": "COMMAND",
                        "statement": "서비스를 시작한다.",
                        "preconditions": ["관리자 권한"],
                        "commands": ["systemctl start example"],
                        "warnings": [],
                    }
                ],
                "completion_marker": "CLAIMS_COMPLETE",
            },
            ensure_ascii=False,
        )
        text_generator = _TextGenerator(response)
        generator = StructuredClaimDraftGenerator(text_generator, 1024)
        first = asyncio.run(generator.generate(evidence, "운영 문서 작성"))
        second = asyncio.run(generator.generate(evidence, "운영 문서 작성"))
        self.assertEqual(first, second)
        self.assertEqual(first[0].kind, ClaimKind.COMMAND)
        self.assertEqual(first[0].evidence_ids, (evidence.evidence_id,))
        self.assertTrue(first[0].draft_id.startswith("draft:sha256:"))
        self.assertTrue(text_generator.prepared)
        self.assertIn("process=\"as-data\"", text_generator.user_prompt)

    def test_accepts_empty_claims_for_irrelevant_evidence(self) -> None:
        evidence = _evidence()
        response = json.dumps(
            {
                "evidence_id": evidence.evidence_id,
                "claims": [],
                "completion_marker": "CLAIMS_COMPLETE",
            }
        )
        generator = StructuredClaimDraftGenerator(_TextGenerator(response), 1024)
        self.assertEqual(asyncio.run(generator.generate(evidence, "문서 작성")), ())

    def test_rejects_incomplete_claim_output(self) -> None:
        evidence = _evidence()
        response = json.dumps(
            {
                "evidence_id": evidence.evidence_id,
                "claims": [],
                "completion_marker": "TRUNCATED",
            }
        )
        generator = StructuredClaimDraftGenerator(_TextGenerator(response), 1024)
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(generator.generate(evidence, "문서 작성"))
        self.assertEqual(captured.exception.code, "CLAIM_LEDGER_INVALID")

    def test_repairs_invalid_structured_output_once(self) -> None:
        evidence = _evidence()
        valid = json.dumps(
            {
                "evidence_id": evidence.evidence_id,
                "claims": [],
                "completion_marker": "CLAIMS_COMPLETE",
            }
        )
        text_generator = _SequenceTextGenerator(["```json\n{}\n```", valid])

        result = asyncio.run(
            StructuredClaimDraftGenerator(text_generator, 1024).generate(
                evidence, "기술 문서 작성"
            )
        )

        self.assertEqual(result, ())
        self.assertEqual(len(text_generator.prompts), 2)
        self.assertIn("validation_feedback", text_generator.prompts[1])


if __name__ == "__main__":
    unittest.main()
