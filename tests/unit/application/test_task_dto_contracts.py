from __future__ import annotations

import hashlib
import unittest

from enterprise_rag.application.dto.tasks import (
    ClaimCoverageDto,
    CoverageMatrixDto,
    EvidenceCoverageDto,
    FinalDocumentCandidateDto,
    FinalQualityReportDto,
    TaskAttemptResultDto,
    TaskDefinitionDto,
    TaskOutputDto,
    TaskPacketDto,
    TaskPlanDto,
    TaskPlanExecutionDto,
    TaskSectionOutputDto,
    TaskValidationReportDto,
)

CLAIM = "claim:sha256:" + "a" * 64
EVIDENCE = "evidence:sha256:" + "b" * 64


def _packet(**overrides) -> TaskPacketDto:
    values = {
        "task_id": "task-one",
        "title": "제목",
        "objective": "목적",
        "owned_claim_ids": (CLAIM,),
        "context_claim_ids": (),
        "allowed_evidence_ids": (EVIDENCE,),
        "relations": (),
        "required_sections": ("본문",),
        "depends_on_task_ids": (),
    }
    values.update(overrides)
    return TaskPacketDto(**values)


def _section(**overrides) -> TaskSectionOutputDto:
    values = {
        "section_key": "본문",
        "heading": "본문",
        "markdown": "내용",
        "used_claim_ids": (CLAIM,),
        "used_evidence_ids": (EVIDENCE,),
    }
    values.update(overrides)
    return TaskSectionOutputDto(**values)


class TaskDtoContractsTest(unittest.TestCase):
    def test_rejects_invalid_task_definition_fields(self) -> None:
        cases = (
            {"task_id": "x"},
            {"title": " "},
            {"owned_claim_ids": ()},
            {"owned_claim_ids": (CLAIM, CLAIM)},
            {"required_sections": ()},
            {"required_sections": (" ",)},
            {"depends_on_task_ids": ("task-one",)},
        )
        base = {
            "task_id": "task-one",
            "title": "제목",
            "objective": "목적",
            "owned_claim_ids": (CLAIM,),
            "required_sections": ("본문",),
            "depends_on_task_ids": (),
        }
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                TaskDefinitionDto(**(base | changes))

    def test_rejects_invalid_packet_coverage_and_plan(self) -> None:
        packet_cases = (
            {"task_id": "x"},
            {"output_schema_version": 2},
            {"owned_claim_ids": ()},
            {"allowed_evidence_ids": ()},
            {"required_sections": ("본문", "본문")},
            {"context_claim_ids": (CLAIM,)},
        )
        for changes in packet_cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _packet(**changes)
        with self.assertRaises(ValueError):
            EvidenceCoverageDto(EVIDENCE, ())
        with self.assertRaises(ValueError):
            CoverageMatrixDto((), (), 1, 0)
        with self.assertRaises(ValueError):
            CoverageMatrixDto((), (), 0, 1)
        with self.assertRaises(ValueError):
            CoverageMatrixDto(
                (ClaimCoverageDto(CLAIM, "task-one"),) * 2,
                (),
                2,
                0,
            )
        coverage = CoverageMatrixDto(
            (ClaimCoverageDto(CLAIM, "task-one"),),
            (EvidenceCoverageDto(EVIDENCE, ("task-one",)),),
            1,
            1,
        )
        with self.assertRaises(ValueError):
            TaskPlanDto((), coverage)
        with self.assertRaises(ValueError):
            TaskPlanDto((_packet(), _packet()), coverage)

    def test_rejects_invalid_task_outputs_and_execution_summaries(self) -> None:
        for changes in (
            {"section_key": ""},
            {"used_claim_ids": ()},
            {"used_evidence_ids": ()},
            {"used_claim_ids": (CLAIM, CLAIM)},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _section(**changes)
        with self.assertRaises(ValueError):
            TaskOutputDto("", (_section(),), (), "TASK_COMPLETE")
        with self.assertRaises(ValueError):
            TaskOutputDto("task-one", (_section(), _section()), (), "TASK_COMPLETE")
        with self.assertRaises(ValueError):
            TaskOutputDto("task-one", (_section(),), (CLAIM, CLAIM), "TASK_COMPLETE")
        valid_output = TaskOutputDto("task-one", (_section(),), (), "TASK_COMPLETE")
        valid_report = TaskValidationReportDto("task-one", True, ())
        with self.assertRaises(ValueError):
            TaskValidationReportDto("task-one", True, ("ERROR",))
        with self.assertRaises(ValueError):
            TaskValidationReportDto("task-one", False, ("ERROR", "ERROR"))
        with self.assertRaises(ValueError):
            TaskAttemptResultDto(0, valid_output, valid_report)
        with self.assertRaises(ValueError):
            TaskAttemptResultDto(1, valid_output, TaskValidationReportDto("other", True, ()))
        with self.assertRaises(ValueError):
            TaskPlanExecutionDto((valid_output,) * 2, (valid_report,) * 2, 2, True)
        with self.assertRaises(ValueError):
            TaskPlanExecutionDto((valid_output,), (), 1, False)
        with self.assertRaises(ValueError):
            TaskPlanExecutionDto((valid_output,), (valid_report,), 0, True)
        invalid_report = TaskValidationReportDto("task-one", False, ("ERROR",))
        with self.assertRaises(ValueError):
            TaskPlanExecutionDto((valid_output,), (invalid_report,), 1, True)

    def test_rejects_inconsistent_final_quality_and_candidate(self) -> None:
        digest = hashlib.sha256(b"# document\n").hexdigest()
        base = {
            "valid": True,
            "error_codes": (),
            "document_sha256": digest,
            "source_document_count": 1,
            "evidence_count": 1,
            "claim_count": 1,
            "task_count": 1,
            "validated_task_count": 1,
            "covered_claim_count": 1,
            "covered_evidence_count": 1,
        }
        for changes in (
            {"valid": True, "error_codes": ("ERROR",)},
            {"valid": False, "error_codes": ("ERROR", "ERROR")},
            {"document_sha256": "bad"},
            {"source_document_count": -1},
            {"validated_task_count": 2},
            {"covered_claim_count": 2},
            {"covered_evidence_count": 2},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                FinalQualityReportDto(**(base | changes))
        quality = FinalQualityReportDto(**base)
        with self.assertRaises(ValueError):
            FinalDocumentCandidateDto(" ", quality)
        with self.assertRaises(ValueError):
            FinalDocumentCandidateDto("# changed\n", quality)


if __name__ == "__main__":
    unittest.main()
