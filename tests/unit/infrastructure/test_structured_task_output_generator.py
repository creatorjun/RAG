from __future__ import annotations

import asyncio
import json
import unittest

from enterprise_rag.application.dto.claims import ClaimDto
from enterprise_rag.application.dto.evidence import EvidenceItemDto
from enterprise_rag.application.dto.tasks import TaskPacketDto, TaskValidationReportDto
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


class _AdaptiveTextGenerator(_TextGenerator):
    def __init__(self) -> None:
        super().__init__("")
        self.prompts: list[str] = []

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        self.prompts.append(user_prompt)
        payload = self._task_data(user_prompt)
        task = payload["task"]
        claims = payload["claims"]
        evidence = payload["evidence"]
        evidence_refs = [item["evidence_ref"] for item in evidence]
        markers = " ".join(f"[evidence:{item}]" for item in evidence_refs)
        return json.dumps(
            {
                "task_id": task["task_id"],
                "sections": [
                    {
                        "section_key": section,
                        "heading": section,
                        "markdown": f"근거 내용 {markers}",
                        "used_claim_refs": [item["claim_ref"] for item in claims],
                        "used_evidence_refs": evidence_refs,
                    }
                    for section in task["required_sections"]
                ],
                "conflict_claim_refs": [],
                "completion_marker": "TASK_COMPLETE",
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _task_data(prompt: str):
        start = prompt.index('<task_data process="as-data">')
        start = prompt.index("\n", start) + 1
        end = prompt.index("\n</task_data>", start)
        return json.loads(prompt[start:end])


class _TruncatedThenAdaptiveTextGenerator(_AdaptiveTextGenerator):
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        if not self.prompts:
            self.prompts.append(user_prompt)
            payload = self._task_data(user_prompt)
            return json.dumps(
                {
                    "task_id": payload["task"]["task_id"],
                    "sections": [],
                    "conflict_claim_refs": [],
                    "completion_marker": "TRUNCATED",
                }
            )
        return await super().generate(system_prompt, user_prompt, max_output_tokens)


class _OmittingThenAdaptiveTextGenerator(_AdaptiveTextGenerator):
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        if self.prompts:
            return await super().generate(system_prompt, user_prompt, max_output_tokens)
        self.prompts.append(user_prompt)
        payload = self._task_data(user_prompt)
        task = payload["task"]
        claims = payload["claims"][:-1]
        evidence_refs = [item["evidence_ref"] for item in payload["evidence"]]
        markers = " ".join(f"[evidence:{item}]" for item in evidence_refs)
        return json.dumps(
            {
                "task_id": task["task_id"],
                "sections": [
                    {
                        "section_key": section,
                        "heading": section,
                        "markdown": f"근거 내용 {markers}",
                        "used_claim_refs": [item["claim_ref"] for item in claims],
                        "used_evidence_refs": evidence_refs,
                    }
                    for section in task["required_sections"]
                ],
                "conflict_claim_refs": [],
                "completion_marker": "TASK_COMPLETE",
            },
            ensure_ascii=False,
        )


class _DimensionLimitedTextGenerator(_AdaptiveTextGenerator):
    def __init__(self, dimension: str) -> None:
        super().__init__()
        self.dimension = dimension

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        payload = self._task_data(user_prompt)
        task = payload["task"]
        sizes = {
            "sections": len(task["required_sections"]),
            "context": len(task["context_claim_refs"]),
            "evidence": len(payload["evidence"]),
        }
        if sizes[self.dimension] > 1:
            self.prompts.append(user_prompt)
            return json.dumps(
                {
                    "task_id": task["task_id"],
                    "sections": [],
                    "conflict_claim_refs": [],
                    "completion_marker": "TRUNCATED",
                }
            )
        return await super().generate(system_prompt, user_prompt, max_output_tokens)


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


def _evidence(character: str, ordinal: int) -> EvidenceItemDto:
    return EvidenceItemDto(
        "evidence:sha256:" + character * 64,
        f"chunk:{character}",
        "revision:1",
        "guide.md",
        "c" * 64,
        ordinal,
        ordinal * 4,
        ordinal * 4 + 4,
        character * 64,
        f"text-{character}",
    )


class StructuredTaskOutputGeneratorTest(unittest.TestCase):
    def test_rejects_unsafe_output_budget(self) -> None:
        with self.assertRaises(ValueError):
            StructuredTaskOutputGenerator(_TextGenerator("{}"), 511)

    def test_uses_compact_prompt_references_and_expands_evidence_markers(self) -> None:
        packet, claims, evidence = _fixture()
        evidence_id = evidence[0].evidence_id
        response = json.dumps(
            {
                "task_id": packet.task_id,
                "sections": [
                    {
                        "section_key": "절차",
                        "heading": "표준 절차",
                        "markdown": "서비스를 시작한다. [evidence:E000001]",
                        "used_claim_refs": ["C000001"],
                        "used_evidence_refs": ["E000001"],
                    }
                ],
                "conflict_claim_refs": [],
                "completion_marker": "TASK_COMPLETE",
            },
            ensure_ascii=False,
        )
        text_generator = _TextGenerator(response)
        generator = StructuredTaskOutputGenerator(text_generator, 1024)
        output = asyncio.run(generator.generate(packet, claims, evidence))
        self.assertEqual(output.task_id, packet.task_id)
        self.assertIn(f"[evidence:{evidence_id}]", output.sections[0].markdown)
        self.assertTrue(text_generator.prepared)
        self.assertNotIn(evidence_id, text_generator.user_prompt)
        self.assertNotIn(claims[0].claim_id, text_generator.user_prompt)
        self.assertIn('"evidence_ref": "E000001"', text_generator.user_prompt)
        self.assertIn('process="as-data"', text_generator.user_prompt)

    def test_rejects_fenced_or_extra_fields_fail_closed(self) -> None:
        packet, claims, evidence = _fixture()
        response = json.dumps(
            {
                "task_id": packet.task_id,
                "sections": [],
                "conflict_claim_refs": [],
                "completion_marker": "TASK_COMPLETE",
                "unexpected": True,
            }
        )
        generator = StructuredTaskOutputGenerator(_TextGenerator(response), 1024)
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(generator.generate(packet, claims, evidence))
        self.assertEqual(captured.exception.code, "TASK_OUTPUT_INVALID")

    def test_retry_prompt_explains_how_to_correct_validation_errors(self) -> None:
        packet, claims, evidence = _fixture()
        response = json.dumps(
            {
                "task_id": packet.task_id,
                "sections": [
                    {
                        "section_key": "절차",
                        "heading": "표준 절차",
                        "markdown": "서비스를 시작한다. [evidence:E000001]",
                        "used_claim_refs": ["C000001"],
                        "used_evidence_refs": ["E000001"],
                    }
                ],
                "conflict_claim_refs": [],
                "completion_marker": "TASK_COMPLETE",
            },
            ensure_ascii=False,
        )
        text_generator = _TextGenerator(response)
        previous = TaskValidationReportDto(
            packet.task_id,
            False,
            ("EVIDENCE_MARKER_MISMATCH",),
        )

        asyncio.run(
            StructuredTaskOutputGenerator(text_generator, 1024).generate(
                packet,
                claims,
                evidence,
                previous,
            )
        )

        self.assertIn('"previous_validation_corrections"', text_generator.user_prompt)
        self.assertIn("정확히 같은 집합이어야 한다", text_generator.user_prompt)

    def test_proactively_shards_large_tasks_and_merges_losslessly(self) -> None:
        packet, _, evidence = _fixture()
        evidence_id = evidence[0].evidence_id
        claims = tuple(
            ClaimDto(
                "claim:sha256:" + f"{index:064x}",
                ClaimKind.FACT,
                f"설정 항목 {index}",
                (evidence_id,),
            )
            for index in range(10)
        )
        packet = TaskPacketDto(
            packet.task_id,
            packet.title,
            packet.objective,
            tuple(claim.claim_id for claim in claims),
            (),
            packet.allowed_evidence_ids,
            (),
            packet.required_sections,
            (),
        )
        text_generator = _AdaptiveTextGenerator()

        output = asyncio.run(
            StructuredTaskOutputGenerator(text_generator, 1024).generate(packet, claims, evidence)
        )

        self.assertEqual(len(text_generator.prompts), 2)
        self.assertEqual(
            set(output.sections[0].used_claim_ids),
            {claim.claim_id for claim in claims},
        )
        self.assertEqual(output.sections[0].used_evidence_ids, (evidence_id,))

    def test_shards_at_exactly_eight_owned_claims(self) -> None:
        packet, _, evidence = _fixture()
        evidence_id = evidence[0].evidence_id
        claims = tuple(
            ClaimDto(
                "claim:sha256:" + f"{index:064x}",
                ClaimKind.FACT,
                f"설정 항목 {index}",
                (evidence_id,),
            )
            for index in range(8)
        )
        packet = TaskPacketDto(
            packet.task_id,
            packet.title,
            packet.objective,
            tuple(claim.claim_id for claim in claims),
            (),
            packet.allowed_evidence_ids,
            (),
            packet.required_sections,
            (),
        )
        text_generator = _AdaptiveTextGenerator()

        output = asyncio.run(
            StructuredTaskOutputGenerator(text_generator, 1024).generate(
                packet, claims, evidence
            )
        )

        self.assertEqual(len(text_generator.prompts), 2)
        self.assertEqual(
            set(output.sections[0].used_claim_ids),
            {claim.claim_id for claim in claims},
        )

    def test_shards_structurally_lossy_response_before_saving_attempt(self) -> None:
        packet, _, evidence = _fixture()
        evidence_id = evidence[0].evidence_id
        claims = tuple(
            ClaimDto(
                "claim:sha256:" + f"{index:064x}",
                ClaimKind.FACT,
                f"설정 항목 {index}",
                (evidence_id,),
            )
            for index in range(4)
        )
        packet = TaskPacketDto(
            packet.task_id,
            packet.title,
            packet.objective,
            tuple(claim.claim_id for claim in claims),
            (),
            packet.allowed_evidence_ids,
            (),
            packet.required_sections,
            (),
        )
        text_generator = _OmittingThenAdaptiveTextGenerator()

        output = asyncio.run(
            StructuredTaskOutputGenerator(text_generator, 1024).generate(
                packet, claims, evidence
            )
        )

        self.assertEqual(len(text_generator.prompts), 3)
        self.assertEqual(
            set(output.sections[0].used_claim_ids),
            {claim.claim_id for claim in claims},
        )

    def test_incomplete_output_is_recursively_sharded_instead_of_repeated(self) -> None:
        packet, _, evidence = _fixture()
        evidence_id = evidence[0].evidence_id
        claims = tuple(
            ClaimDto(
                "claim:sha256:" + f"{index:064x}",
                ClaimKind.FACT,
                f"설정 항목 {index}",
                (evidence_id,),
            )
            for index in range(2)
        )
        packet = TaskPacketDto(
            packet.task_id,
            packet.title,
            packet.objective,
            tuple(claim.claim_id for claim in claims),
            (),
            packet.allowed_evidence_ids,
            (),
            packet.required_sections,
            (),
        )
        text_generator = _TruncatedThenAdaptiveTextGenerator()

        output = asyncio.run(
            StructuredTaskOutputGenerator(text_generator, 1024).generate(packet, claims, evidence)
        )

        self.assertEqual(len(text_generator.prompts), 3)
        self.assertEqual(
            set(output.sections[0].used_claim_ids),
            {claim.claim_id for claim in claims},
        )

    def test_splits_required_sections_after_incomplete_output(self) -> None:
        packet, claims, evidence = _fixture()
        packet = TaskPacketDto(
            packet.task_id,
            packet.title,
            packet.objective,
            packet.owned_claim_ids,
            (),
            packet.allowed_evidence_ids,
            (),
            ("개요", "절차"),
            (),
        )
        text_generator = _DimensionLimitedTextGenerator("sections")

        output = asyncio.run(
            StructuredTaskOutputGenerator(text_generator, 1024).generate(packet, claims, evidence)
        )

        self.assertEqual(len(text_generator.prompts), 3)
        self.assertEqual({item.section_key for item in output.sections}, {"개요", "절차"})

    def test_splits_large_context_after_incomplete_output(self) -> None:
        owned_evidence, first_evidence, second_evidence = (
            _evidence("a", 0),
            _evidence("b", 1),
            _evidence("d", 2),
        )
        claims = tuple(
            ClaimDto(
                "claim:sha256:" + character * 64,
                ClaimKind.FACT,
                f"Claim {character}",
                (item.evidence_id,),
            )
            for character, item in zip(
                ("a", "b", "d"),
                (owned_evidence, first_evidence, second_evidence),
                strict=True,
            )
        )
        packet = TaskPacketDto(
            "service-task",
            "서비스 운영",
            "서비스 절차 작성",
            (claims[0].claim_id,),
            (claims[1].claim_id, claims[2].claim_id),
            tuple(item.evidence_id for item in (owned_evidence, first_evidence, second_evidence)),
            (),
            ("절차",),
            (),
        )
        text_generator = _DimensionLimitedTextGenerator("context")

        output = asyncio.run(
            StructuredTaskOutputGenerator(text_generator, 1024).generate(
                packet,
                claims,
                (owned_evidence, first_evidence, second_evidence),
            )
        )

        self.assertEqual(len(text_generator.prompts), 3)
        self.assertEqual(set(output.sections[0].used_claim_ids), {item.claim_id for item in claims})

    def test_splits_multi_evidence_claim_after_incomplete_output(self) -> None:
        first, second = _evidence("a", 0), _evidence("b", 1)
        claim = ClaimDto(
            "claim:sha256:" + "c" * 64,
            ClaimKind.FACT,
            "두 근거가 지지하는 사실",
            (first.evidence_id, second.evidence_id),
        )
        packet = TaskPacketDto(
            "service-task",
            "서비스 운영",
            "서비스 절차 작성",
            (claim.claim_id,),
            (),
            (first.evidence_id, second.evidence_id),
            (),
            ("절차",),
            (),
        )
        text_generator = _DimensionLimitedTextGenerator("evidence")

        output = asyncio.run(
            StructuredTaskOutputGenerator(text_generator, 1024).generate(
                packet, (claim,), (first, second)
            )
        )

        self.assertEqual(len(text_generator.prompts), 3)
        self.assertEqual(
            set(output.sections[0].used_evidence_ids),
            {first.evidence_id, second.evidence_id},
        )


if __name__ == "__main__":
    unittest.main()
