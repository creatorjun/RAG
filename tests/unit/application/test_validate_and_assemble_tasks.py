from __future__ import annotations

import unittest

from enterprise_rag.application.dto.claims import ClaimDto, ClaimLedgerDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto, EvidenceItemDto
from enterprise_rag.application.dto.tasks import (
    ClaimCoverageDto,
    CoverageMatrixDto,
    EvidenceCoverageDto,
    TaskOutputDto,
    TaskPacketDto,
    TaskPlanDto,
    TaskPlanExecutionDto,
    TaskSectionOutputDto,
)
from enterprise_rag.application.use_cases.assemble_document import AssembleDocument
from enterprise_rag.application.use_cases.build_final_document_candidate import (
    BuildFinalDocumentCandidate,
)
from enterprise_rag.application.use_cases.validate_final_document import (
    ValidateFinalDocument,
)
from enterprise_rag.application.use_cases.validate_task_output import ValidateTaskOutput
from enterprise_rag.domain.claims import ClaimKind
from enterprise_rag.domain.errors import ApplicationError


def _fixture() -> tuple[EvidenceBundleDto, ClaimLedgerDto, TaskPlanDto]:
    evidence_id = "evidence:sha256:" + "a" * 64
    claim_id = "claim:sha256:" + "b" * 64
    evidence_item = EvidenceItemDto(
        evidence_id=evidence_id,
        chunk_id="chunk:1",
        revision_id="revision:1",
        relative_path="guide.md",
        source_sha256="c" * 64,
        ordinal=0,
        start_char=0,
        end_char=4,
        content_sha256="d" * 64,
        text="text",
    )
    evidence = EvidenceBundleDto((evidence_item,), 1, 1)
    claim = ClaimDto(
        claim_id,
        ClaimKind.PROCEDURE,
        "서비스를 시작한다.",
        (evidence_id,),
        preconditions=("관리자 권한",),
        commands=("systemctl start example",),
        warnings=("운영 시간에 주의",),
    )
    ledger = ClaimLedgerDto((claim,), (), (evidence_id,))
    packet = TaskPacketDto(
        task_id="service-task",
        title="서비스 운영",
        objective="서비스 절차 작성",
        owned_claim_ids=(claim_id,),
        context_claim_ids=(),
        allowed_evidence_ids=(evidence_id,),
        relations=(),
        required_sections=("절차",),
        depends_on_task_ids=(),
    )
    coverage = CoverageMatrixDto(
        (ClaimCoverageDto(claim_id, packet.task_id),),
        (EvidenceCoverageDto(evidence_id, (packet.task_id,)),),
        1,
        1,
    )
    return evidence, ledger, TaskPlanDto((packet,), coverage)


def _valid_output(plan: TaskPlanDto) -> TaskOutputDto:
    packet = plan.tasks[0]
    evidence_id = packet.allowed_evidence_ids[0]
    return TaskOutputDto(
        task_id=packet.task_id,
        sections=(
            TaskSectionOutputDto(
                section_key="절차",
                heading="표준 절차",
                markdown=(
                    "관리자 권한으로 실행하고 운영 시간에 주의합니다. "
                    "다음 명령으로 서비스를 시작합니다. "
                    f"[evidence:{evidence_id}]\n\n```bash\nsystemctl start example\n```"
                ),
                used_claim_ids=packet.owned_claim_ids,
                used_evidence_ids=(evidence_id,),
            ),
        ),
        conflict_claim_ids=(),
        completion_marker="TASK_COMPLETE",
    )


class ValidateAndAssembleTaskTest(unittest.TestCase):
    def test_validates_and_deterministically_assembles_source_citations(self) -> None:
        evidence, ledger, plan = _fixture()
        output = _valid_output(plan)
        report = ValidateTaskOutput().execute(plan.tasks[0], ledger, output)
        self.assertTrue(report.valid)
        first = AssembleDocument().execute(
            "통합 가이드", plan, evidence, (output,), (report,)
        )
        second = AssembleDocument().execute(
            "통합 가이드", plan, evidence, (output,), (report,)
        )
        self.assertEqual(first, second)
        self.assertIn("[source:guide.md]", first)
        self.assertNotIn("[evidence:", first)
        self.assertIn("## 원본 문서 목록\n\n- `guide.md`", first)
        quality = ValidateFinalDocument().execute(
            first,
            plan,
            ledger,
            evidence,
            (output,),
            (report,),
        )
        self.assertTrue(quality.valid)
        self.assertEqual(quality.covered_claim_count, 1)
        self.assertEqual(quality.covered_evidence_count, 1)
        self.assertEqual(quality.validated_task_count, 1)
        candidate = BuildFinalDocumentCandidate(
            AssembleDocument(),
            ValidateFinalDocument(),
        ).execute(
            "통합 가이드",
            plan,
            ledger,
            evidence,
            TaskPlanExecutionDto((output,), (report,), 1, True),
        )
        self.assertEqual(candidate.markdown, first)
        self.assertTrue(candidate.quality.valid)

    def test_excludes_irrelevant_evidence_from_inventory_and_quality_coverage(self) -> None:
        evidence, ledger, plan = _fixture()
        irrelevant = EvidenceItemDto(
            evidence_id="evidence:sha256:" + "e" * 64,
            chunk_id="chunk:noise",
            revision_id="revision:noise",
            relative_path="lunch-menu.md",
            source_sha256="f" * 64,
            ordinal=0,
            start_char=0,
            end_char=4,
            content_sha256="1" * 64,
            text="점심 메뉴",
        )
        mixed_evidence = EvidenceBundleDto(
            (*evidence.items, irrelevant),
            2,
            2,
        )
        output = _valid_output(plan)
        report = ValidateTaskOutput().execute(plan.tasks[0], ledger, output)

        markdown = AssembleDocument().execute(
            "통합 가이드",
            plan,
            mixed_evidence,
            (output,),
            (report,),
        )
        quality = ValidateFinalDocument().execute(
            markdown,
            plan,
            ledger,
            mixed_evidence,
            (output,),
            (report,),
        )

        self.assertNotIn("lunch-menu.md", markdown)
        self.assertTrue(quality.valid)
        self.assertEqual(quality.evidence_count, 1)
        self.assertEqual(quality.source_document_count, 2)

    def test_reports_missing_marker_claim_and_completion_without_throwing(self) -> None:
        _, ledger, plan = _fixture()
        packet = plan.tasks[0]
        invalid = TaskOutputDto(
            task_id=packet.task_id,
            sections=(
                TaskSectionOutputDto(
                    "다른 섹션",
                    "다른 섹션",
                    "근거 마커가 없습니다.",
                    packet.owned_claim_ids,
                    packet.allowed_evidence_ids,
                ),
            ),
            conflict_claim_ids=(),
            completion_marker="",
        )
        report = ValidateTaskOutput().execute(packet, ledger, invalid)
        self.assertFalse(report.valid)
        self.assertIn("OUTPUT_INCOMPLETE", report.error_codes)
        self.assertIn("REQUIRED_SECTION_MISSING", report.error_codes)
        self.assertIn("UNPLANNED_SECTION", report.error_codes)
        self.assertIn("EVIDENCE_MARKER_MISMATCH", report.error_codes)

    def test_assembler_rejects_unvalidated_output(self) -> None:
        evidence, ledger, plan = _fixture()
        output = _valid_output(plan)
        invalid = TaskOutputDto(
            output.task_id,
            output.sections,
            output.conflict_claim_ids,
            "TRUNCATED",
        )
        report = ValidateTaskOutput().execute(plan.tasks[0], ledger, invalid)
        with self.assertRaises(ApplicationError) as captured:
            AssembleDocument().execute(
                "통합 가이드", plan, evidence, (invalid,), (report,)
            )
        self.assertEqual(captured.exception.code, "DOCUMENT_ASSEMBLY_FAILED")

    def test_final_quality_gate_reports_tampering_and_incomplete_coverage(self) -> None:
        evidence, ledger, plan = _fixture()
        output = _valid_output(plan)
        report = ValidateTaskOutput().execute(plan.tasks[0], ledger, output)
        assembled = AssembleDocument().execute(
            "통합 가이드", plan, evidence, (output,), (report,)
        )
        tampered = assembled.replace("[source:guide.md]", "[source:unknown.md]")
        quality = ValidateFinalDocument().execute(
            tampered,
            plan,
            ledger,
            evidence,
            (),
            (report,),
        )
        self.assertFalse(quality.valid)
        self.assertIn("TASK_OUTPUT_COVERAGE_INCOMPLETE", quality.error_codes)
        self.assertIn("CLAIM_COVERAGE_INCOMPLETE", quality.error_codes)
        self.assertIn("EVIDENCE_COVERAGE_INCOMPLETE", quality.error_codes)
        self.assertIn("SOURCE_NOT_ALLOWED", quality.error_codes)
        self.assertIn("SOURCE_COVERAGE_INCOMPLETE", quality.error_codes)

    def test_validator_requires_owned_claim_operational_details_verbatim(self) -> None:
        _, ledger, plan = _fixture()
        packet = plan.tasks[0]
        evidence_id = packet.allowed_evidence_ids[0]
        output = TaskOutputDto(
            packet.task_id,
            (
                TaskSectionOutputDto(
                    "절차",
                    "표준 절차",
                    f"서비스를 처리한다. [evidence:{evidence_id}]",
                    packet.owned_claim_ids,
                    (evidence_id,),
                ),
            ),
            (),
            "TASK_COMPLETE",
        )
        report = ValidateTaskOutput().execute(packet, ledger, output)
        self.assertFalse(report.valid)
        self.assertIn("CLAIM_PRECONDITION_MISSING", report.error_codes)
        self.assertIn("CLAIM_COMMAND_MISSING", report.error_codes)
        self.assertIn("CLAIM_WARNING_MISSING", report.error_codes)

    def test_validator_ignores_citation_before_operational_detail_punctuation(self) -> None:
        _, ledger, plan = _fixture()
        packet = plan.tasks[0]
        evidence_id = packet.allowed_evidence_ids[0]
        original = ledger.claims[0]
        claim = ClaimDto(
            original.claim_id,
            original.kind,
            original.statement,
            original.evidence_ids,
            preconditions=("서비스를 시작한다.",),
        )
        output = TaskOutputDto(
            packet.task_id,
            (
                TaskSectionOutputDto(
                    "절차",
                    "표준 절차",
                    f"서비스를 시작한다 [evidence:{evidence_id}].",
                    packet.owned_claim_ids,
                    (evidence_id,),
                ),
            ),
            (),
            "TASK_COMPLETE",
        )

        report = ValidateTaskOutput().execute(
            packet,
            ClaimLedgerDto((claim,), ledger.relations, ledger.reviewed_evidence_ids),
            output,
        )

        self.assertTrue(report.valid)

    def test_assembler_uses_planned_section_order_not_model_array_order(self) -> None:
        evidence, ledger, base_plan = _fixture()
        packet = base_plan.tasks[0]
        reordered_packet = TaskPacketDto(
            packet.task_id,
            packet.title,
            packet.objective,
            packet.owned_claim_ids,
            packet.context_claim_ids,
            packet.allowed_evidence_ids,
            packet.relations,
            ("준비", "절차"),
            packet.depends_on_task_ids,
        )
        plan = TaskPlanDto((reordered_packet,), base_plan.coverage)
        evidence_id = packet.allowed_evidence_ids[0]
        output = TaskOutputDto(
            packet.task_id,
            (
                TaskSectionOutputDto(
                    "절차",
                    "두 번째",
                    f"systemctl start example [evidence:{evidence_id}]",
                    packet.owned_claim_ids,
                    (evidence_id,),
                ),
                TaskSectionOutputDto(
                    "준비",
                    "첫 번째",
                    (
                        "관리자 권한이며 운영 시간에 주의한다. "
                        f"[evidence:{evidence_id}]"
                    ),
                    packet.owned_claim_ids,
                    (evidence_id,),
                ),
            ),
            (),
            "TASK_COMPLETE",
        )
        report = ValidateTaskOutput().execute(reordered_packet, ledger, output)
        self.assertTrue(report.valid)
        markdown = AssembleDocument().execute(
            "통합 가이드", plan, evidence, (output,), (report,)
        )
        self.assertLess(markdown.index("### 첫 번째"), markdown.index("### 두 번째"))

    def test_validator_reports_unauthorized_and_malformed_model_references(self) -> None:
        _, ledger, plan = _fixture()
        packet = plan.tasks[0]
        foreign_evidence = "evidence:sha256:" + "f" * 64
        invalid = TaskOutputDto(
            "different-task",
            (
                TaskSectionOutputDto(
                    "절차",
                    "절차",
                    "[evidence:bad] [source:guide.md] ```",
                    ("claim:sha256:" + "e" * 64,),
                    (foreign_evidence,),
                ),
            ),
            ("claim:sha256:" + "d" * 64,),
            "TASK_COMPLETE",
        )
        report = ValidateTaskOutput().execute(packet, ledger, invalid)
        expected = {
            "TASK_ID_MISMATCH",
            "CLAIM_NOT_ALLOWED",
            "EVIDENCE_NOT_ALLOWED",
            "EVIDENCE_MARKER_MALFORMED",
            "SOURCE_MARKER_NOT_ALLOWED",
            "MARKDOWN_INCOMPLETE",
            "EVIDENCE_MARKER_MISMATCH",
            "CLAIM_NOT_FOUND",
            "OWNED_CLAIM_MISSING",
            "OWNED_EVIDENCE_MISSING",
            "CONFLICT_CLAIM_NOT_ALLOWED",
        }
        self.assertTrue(expected.issubset(set(report.error_codes)))

    def test_final_gate_rejects_incomplete_structure_and_internal_markers(self) -> None:
        evidence, ledger, plan = _fixture()
        output = _valid_output(plan)
        report = ValidateTaskOutput().execute(plan.tasks[0], ledger, output)
        quality = ValidateFinalDocument().execute(
            "본문 [source:broken\n[evidence:internal] ```",
            plan,
            ledger,
            evidence,
            (output,),
            (report,),
        )
        self.assertFalse(quality.valid)
        for code in (
            "SOURCE_MARKER_MALFORMED",
            "SOURCE_COVERAGE_INCOMPLETE",
            "EVIDENCE_MARKER_REMAINS",
            "MARKDOWN_INCOMPLETE",
            "DOCUMENT_STRUCTURE_INCOMPLETE",
            "TASK_SECTION_MISSING",
        ):
            self.assertIn(code, quality.error_codes)


if __name__ == "__main__":
    unittest.main()
