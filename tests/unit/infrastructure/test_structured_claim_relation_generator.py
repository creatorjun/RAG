from __future__ import annotations

import asyncio
import json
import unittest

from enterprise_rag.application.dto.claims import ClaimDraftDto, ClaimRelationDraftDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto, EvidenceItemDto
from enterprise_rag.domain.claims import ClaimKind, ClaimRelationType
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.infrastructure.models.structured_claim_relation_generator import (
    StructuredClaimRelationGenerator,
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


class _SequenceTextGenerator(_TextGenerator):
    def __init__(self, responses: list[str]) -> None:
        super().__init__(responses[-1])
        self.responses = iter(responses)
        self.prompts: list[str] = []

    async def generate(self, system_prompt, user_prompt, max_output_tokens):
        self.prompts.append(user_prompt)
        return next(self.responses)


class _OverflowThenEmptyGenerator(_TextGenerator):
    def __init__(self) -> None:
        super().__init__("")
        self.prompts: list[str] = []

    async def generate(self, system_prompt, user_prompt, max_output_tokens):
        self.prompts.append(user_prompt)
        if len(self.prompts) == 1:
            raise revision_error("TOKEN_BUDGET_EXCEEDED")
        return json.dumps({"relations": [], "completion_marker": "RELATIONS_COMPLETE"})


class _TruncatedThenEmptyGenerator(_TextGenerator):
    def __init__(self) -> None:
        super().__init__("")
        self.prompts: list[str] = []

    async def generate(self, system_prompt, user_prompt, max_output_tokens):
        self.prompts.append(user_prompt)
        if len(self.prompts) <= 2:
            return '{"completion_marker":"RELATIONS_COMPLETE","relations":[["C000001"'
        return json.dumps({"relations": [], "completion_marker": "RELATIONS_COMPLETE"})


class _OverflowUntilPairGenerator(_TextGenerator):
    def __init__(self) -> None:
        super().__init__("")
        self.prompts: list[str] = []

    async def generate(self, system_prompt, user_prompt, max_output_tokens):
        self.prompts.append(user_prompt)
        claims = StructuredClaimRelationGeneratorTest._task_data(user_prompt)["claims"]
        if not isinstance(claims, list):
            raise AssertionError("claims must be a list")
        if len(claims) > 2:
            raise revision_error("TOKEN_BUDGET_EXCEEDED")
        return json.dumps(
            {
                "relations": [[claims[0]["claim_ref"], claims[1]["claim_ref"], "COMPLEMENTARY"]],
                "completion_marker": "RELATIONS_COMPLETE",
            }
        )


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
                "relations": [["C000001", "C000002", "CONFLICT"]],
                "completion_marker": "RELATIONS_COMPLETE",
            }
        )
        text_generator = _TextGenerator(response)
        generator = StructuredClaimRelationGenerator(text_generator, 1024)
        relations = asyncio.run(generator.generate(drafts, evidence, "서비스 운영 문서"))
        self.assertEqual(relations[0].relation, ClaimRelationType.CONFLICT)
        self.assertIn('"claim_ref": "C000001"', text_generator.user_prompt)
        self.assertNotIn('"draft_id": "draft:one"', text_generator.user_prompt)
        self.assertIn("[left_claim_ref, right_claim_ref, relation]", text_generator.user_prompt)

    def test_accepts_legacy_object_relation_during_schema_transition(self) -> None:
        drafts, evidence = _fixture()
        response = json.dumps(
            {
                "relations": [
                    {
                        "left_claim_ref": "C000001",
                        "right_claim_ref": "C000002",
                        "relation": "CONFLICT",
                    }
                ],
                "completion_marker": "RELATIONS_COMPLETE",
            }
        )

        relations = asyncio.run(
            StructuredClaimRelationGenerator(_TextGenerator(response), 1024).generate(
                drafts, evidence, "서비스 운영 문서"
            )
        )

        self.assertEqual(relations[0].relation, ClaimRelationType.CONFLICT)

    def test_rejects_unknown_claim_or_unrelated_output(self) -> None:
        drafts, evidence = _fixture()
        response = json.dumps(
            {
                "relations": [
                    {
                        "left_claim_ref": "C000001",
                        "right_claim_ref": "C999999",
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
        valid = json.dumps({"relations": [], "completion_marker": "RELATIONS_COMPLETE"})
        text_generator = _SequenceTextGenerator(["not-json", valid])

        relations = asyncio.run(
            StructuredClaimRelationGenerator(text_generator, 1024).generate(
                drafts, evidence, "서비스 운영 문서"
            )
        )

        self.assertEqual(relations, ())
        self.assertEqual(len(text_generator.prompts), 2)
        self.assertIn("validation_feedback", text_generator.prompts[1])

    def test_retries_an_oversized_relation_prompt_as_bounded_batches(self) -> None:
        seed_drafts, evidence = _fixture()
        drafts = tuple(
            ClaimDraftDto(
                f"draft:{index:03d}",
                ClaimKind.FACT,
                f"서비스 설정 항목 {index:03d}",
                (seed_drafts[index % 2].evidence_ids[0],),
            )
            for index in range(60)
        )
        text_generator = _OverflowThenEmptyGenerator()

        relations = asyncio.run(
            StructuredClaimRelationGenerator(text_generator, 1024).generate(
                drafts,
                evidence,
                "서비스 운영 문서",
            )
        )

        self.assertEqual(relations, ())
        batch_sizes = [len(self._task_data(prompt)["claims"]) for prompt in text_generator.prompts]
        self.assertTrue(all(size <= 40 for size in batch_sizes))
        self.assertLess(batch_sizes[1], batch_sizes[0])
        self.assertGreater(len(batch_sizes), 2)

    def test_splits_a_batch_after_two_truncated_json_responses(self) -> None:
        seed_drafts, evidence = _fixture()
        drafts = tuple(
            ClaimDraftDto(
                f"draft:{index:03d}",
                ClaimKind.FACT,
                f"서비스 설정 항목 {index:03d}",
                (seed_drafts[0].evidence_ids[0],),
            )
            for index in range(20)
        )
        text_generator = _TruncatedThenEmptyGenerator()

        relations = asyncio.run(
            StructuredClaimRelationGenerator(text_generator, 1024).generate(
                drafts,
                evidence,
                "서비스 운영 문서",
            )
        )

        self.assertEqual(relations, ())
        batch_sizes = [len(self._task_data(prompt)["claims"]) for prompt in text_generator.prompts]
        self.assertEqual(batch_sizes[:2], [20, 20])
        self.assertTrue(any(size < 20 for size in batch_sizes[2:]))
        self.assertTrue(any('"comparison_side": "LEFT"' in p for p in text_generator.prompts))

    def test_recursive_split_preserves_every_pair_without_duplicates(self) -> None:
        seed_drafts, evidence = _fixture()
        drafts = tuple(
            ClaimDraftDto(
                f"draft:{index:03d}",
                ClaimKind.FACT,
                f"서비스 설정 항목 {index:03d}",
                (seed_drafts[0].evidence_ids[0],),
            )
            for index in range(6)
        )
        text_generator = _OverflowUntilPairGenerator()

        relations = asyncio.run(
            StructuredClaimRelationGenerator(text_generator, 1024).generate(
                drafts,
                evidence,
                "서비스 운영 문서",
            )
        )

        pairs = {
            frozenset((relation.left_draft_id, relation.right_draft_id)) for relation in relations
        }
        self.assertEqual(len(relations), 15)
        self.assertEqual(len(pairs), 15)
        self.assertTrue(any('"comparison_side": "LEFT"' in p for p in text_generator.prompts))

    def test_merge_resolves_overlapping_batch_disagreement_conservatively(self) -> None:
        relations = [
            ClaimRelationDraftDto(
                "draft:one",
                "draft:two",
                ClaimRelationType.EXACT_DUPLICATE,
            ),
            ClaimRelationDraftDto(
                "draft:two",
                "draft:one",
                ClaimRelationType.COMPLEMENTARY,
            ),
            ClaimRelationDraftDto(
                "draft:one",
                "draft:two",
                ClaimRelationType.CONFLICT,
            ),
        ]

        merged = StructuredClaimRelationGenerator._merge_relations(relations)
        reversed_merged = StructuredClaimRelationGenerator._merge_relations(
            list(reversed(relations))
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].relation, ClaimRelationType.CONFLICT)
        self.assertEqual(reversed_merged[0].relation, ClaimRelationType.CONFLICT)

    def test_merge_prefers_non_collapsing_relation_over_duplicate_relation(self) -> None:
        merged = StructuredClaimRelationGenerator._merge_relations(
            [
                ClaimRelationDraftDto(
                    "draft:one",
                    "draft:two",
                    ClaimRelationType.SEMANTIC_EQUIVALENT,
                ),
                ClaimRelationDraftDto(
                    "draft:one",
                    "draft:two",
                    ClaimRelationType.CONTEXTUAL_REPEAT,
                ),
            ]
        )

        self.assertEqual(merged[0].relation, ClaimRelationType.CONTEXTUAL_REPEAT)

    def test_candidate_blocks_compare_cross_file_paraphrases_beyond_windows(self) -> None:
        seed_drafts, evidence = _fixture()
        fillers = tuple(
            ClaimDraftDto(
                f"draft:filler:{index:03d}",
                ClaimKind.FACT,
                f"무관한 구성 값 항목 {index:03d}",
                (seed_drafts[index % 2].evidence_ids[0],),
            )
            for index in range(90)
        )
        first = ClaimDraftDto(
            "draft:target:first",
            ClaimKind.COMMAND,
            "alpha 절차에서 nebula-service 재시작 명령을 실행한다.",
            (seed_drafts[0].evidence_ids[0],),
        )
        second = ClaimDraftDto(
            "draft:target:second",
            ClaimKind.COMMAND,
            "zulu 단계는 nebula-service 명령으로 다시 시작한다.",
            (seed_drafts[1].evidence_ids[0],),
        )

        batches = StructuredClaimRelationGenerator._relation_batches(
            (*fillers, first, second), evidence
        )

        self.assertTrue(
            any(
                {first.draft_id, second.draft_id}.issubset({item.draft_id for item in batch})
                for batch in batches
            )
        )

    @staticmethod
    def _task_data(prompt: str) -> dict[str, object]:
        start = prompt.index('<task_data process="as-data">')
        start = prompt.index("\n", start) + 1
        end = prompt.index("\n</task_data>", start)
        value = json.loads(prompt[start:end])
        if not isinstance(value, dict):
            raise AssertionError("task_data must be an object")
        return value


if __name__ == "__main__":
    unittest.main()
