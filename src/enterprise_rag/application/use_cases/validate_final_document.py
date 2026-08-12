from __future__ import annotations

import hashlib
import re

from enterprise_rag.application.dto.claims import ClaimLedgerDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto
from enterprise_rag.application.dto.tasks import (
    FinalQualityReportDto,
    TaskOutputDto,
    TaskPlanDto,
    TaskValidationReportDto,
)

_SOURCE_MARKER = re.compile(r"\[source:([^\]\r\n]+)\]")


class ValidateFinalDocument:
    def execute(
        self,
        markdown: str,
        plan: TaskPlanDto,
        ledger: ClaimLedgerDto,
        evidence: EvidenceBundleDto,
        outputs: tuple[TaskOutputDto, ...],
        validations: tuple[TaskValidationReportDto, ...],
    ) -> FinalQualityReportDto:
        errors: set[str] = set()
        task_ids = {task.task_id for task in plan.tasks}
        output_by_task = {output.task_id: output for output in outputs}
        validation_by_task = {report.task_id: report for report in validations}
        if len(output_by_task) != len(outputs) or set(output_by_task) != task_ids:
            errors.add("TASK_OUTPUT_COVERAGE_INCOMPLETE")
        if (
            len(validation_by_task) != len(validations)
            or set(validation_by_task) != task_ids
            or any(not report.valid for report in validations)
        ):
            errors.add("TASK_VALIDATION_INCOMPLETE")

        claim_ids = {claim.claim_id for claim in ledger.claims}
        all_evidence_ids = {item.evidence_id for item in evidence.items}
        evidence_ids = set(ledger.reviewed_evidence_ids)
        if not evidence_ids or not evidence_ids.issubset(all_evidence_ids):
            errors.add("EVIDENCE_SELECTION_INVALID")
        covered_claims = {
            claim_id
            for output in outputs
            for section in output.sections
            for claim_id in section.used_claim_ids
            if claim_id in claim_ids
        }
        covered_evidence = {
            evidence_id
            for output in outputs
            for section in output.sections
            for evidence_id in section.used_evidence_ids
            if evidence_id in evidence_ids
        }
        if covered_claims != claim_ids:
            errors.add("CLAIM_COVERAGE_INCOMPLETE")
        if covered_evidence != evidence_ids:
            errors.add("EVIDENCE_COVERAGE_INCOMPLETE")
        if (
            plan.coverage.source_claim_count != len(claim_ids)
            or plan.coverage.source_evidence_count != len(evidence_ids)
        ):
            errors.add("COVERAGE_MATRIX_MISMATCH")

        source_paths = {
            item.relative_path
            for item in evidence.items
            if item.evidence_id in evidence_ids
        }
        cited_paths = set(_SOURCE_MARKER.findall(markdown))
        if markdown.count("[source:") != len(_SOURCE_MARKER.findall(markdown)):
            errors.add("SOURCE_MARKER_MALFORMED")
        if not cited_paths.issubset(source_paths):
            errors.add("SOURCE_NOT_ALLOWED")
        if cited_paths != source_paths:
            errors.add("SOURCE_COVERAGE_INCOMPLETE")
        if "[evidence:" in markdown:
            errors.add("EVIDENCE_MARKER_REMAINS")
        if markdown.count("```") % 2:
            errors.add("MARKDOWN_INCOMPLETE")
        if not markdown.startswith("# ") or "## 원본 문서 목록" not in markdown:
            errors.add("DOCUMENT_STRUCTURE_INCOMPLETE")
        for task in plan.tasks:
            if f"## {task.title}" not in markdown:
                errors.add("TASK_SECTION_MISSING")

        digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        validated_count = sum(
            report.valid
            for report in validations
            if report.task_id in task_ids
        )
        return FinalQualityReportDto(
            valid=not errors,
            error_codes=tuple(sorted(errors)),
            document_sha256=digest,
            source_document_count=evidence.source_document_count,
            evidence_count=len(evidence_ids),
            claim_count=len(claim_ids),
            task_count=len(task_ids),
            validated_task_count=validated_count,
            covered_claim_count=len(covered_claims),
            covered_evidence_count=len(covered_evidence),
        )
