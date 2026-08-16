from __future__ import annotations

import asyncio
import json
import unittest

from enterprise_rag.application.dto.claims import ClaimDto
from enterprise_rag.application.dto.web_research import WebSourceDto
from enterprise_rag.domain.claims import ClaimKind
from enterprise_rag.infrastructure.models.structured_web_research_reviewer import (
    StructuredWebResearchReviewer,
)


class _Generator:
    model_id = "fake/model"
    model_revision = "a" * 40

    def __init__(self, response: str) -> None:
        self.response = response
        self.prepared = False
        self.user_prompt = ""

    async def prepare(self) -> None:
        self.prepared = True

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        del system_prompt, max_output_tokens
        self.user_prompt = user_prompt
        return self.response


class StructuredWebResearchReviewerTest(unittest.TestCase):
    def test_parses_independent_web_assessment_and_preserves_query(self) -> None:
        claim = ClaimDto(
            "claim:sha256:" + "b" * 64,
            ClaimKind.FACT,
            "제품 3.2는 지원된다.",
            ("evidence:sha256:" + "a" * 64,),
        )
        source = WebSourceDto(
            "web:sha256:" + "c" * 64,
            "https://docs.example.com/support",
            "Support matrix",
            "Product 3.2 is supported.",
            (claim.claim_id,),
            "2026-08-01",
        )
        response = json.dumps(
            {
                "assessments": [
                    {
                        "claim_ref": "C000001",
                        "verdict": "SUPPORTED",
                        "source_refs": ["W000001"],
                        "note": "같은 버전과 조건을 직접 확인합니다.",
                    }
                ],
                "completion_marker": "WEB_REVIEW_COMPLETE",
            },
            ensure_ascii=False,
        )
        generator = _Generator(response)
        reviewer = StructuredWebResearchReviewer(generator, 1024)

        assessments = asyncio.run(
            reviewer.review(
                (claim,),
                (source,),
                {claim.claim_id: "product 3.2 support"},
            )
        )

        self.assertTrue(generator.prepared)
        self.assertEqual(assessments[0].verdict, "SUPPORTED")
        self.assertEqual(assessments[0].query, "product 3.2 support")
        self.assertEqual(assessments[0].source_ids, (source.source_id,))
        self.assertIn('"source_ref": "W000001"', generator.user_prompt)

    def test_rejects_unsafe_output_budget(self) -> None:
        with self.assertRaises(ValueError):
            StructuredWebResearchReviewer(_Generator("{}"), 511)


if __name__ == "__main__":
    unittest.main()
