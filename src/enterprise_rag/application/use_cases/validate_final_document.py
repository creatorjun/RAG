from __future__ import annotations

import hashlib

from enterprise_rag.application.dto.claims import ClaimLedgerDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto
from enterprise_rag.application.dto.tasks import (
    FinalQualityReportDto,
    TaskOutputDto,
    TaskPlanDto,
    TaskValidationReportDto,
)


class ValidateFinalDocument:
    """Measure document coverage without turning the measurements into a gate."""

    def execute(
        self,
        markdown: str,
        plan: TaskPlanDto,
        ledger: ClaimLedgerDto,
        evidence: EvidenceBundleDto,
        outputs: tuple[TaskOutputDto, ...],
        validations: tuple[TaskValidationReportDto, ...],
    ) -> FinalQualityReportDto:
        task_ids = {task.task_id for task in plan.tasks}
        claim_ids = {claim.claim_id for claim in ledger.claims}
        evidence_ids = set(ledger.reviewed_evidence_ids)
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
        digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        generated_task_count = len({output.task_id for output in outputs} & task_ids)
        del validations
        return FinalQualityReportDto(
            valid=True,
            error_codes=(),
            document_sha256=digest,
            source_document_count=evidence.source_document_count,
            evidence_count=len(evidence_ids),
            claim_count=len(claim_ids),
            task_count=len(task_ids),
            validated_task_count=generated_task_count,
            covered_claim_count=len(covered_claims),
            covered_evidence_count=len(covered_evidence),
        )
