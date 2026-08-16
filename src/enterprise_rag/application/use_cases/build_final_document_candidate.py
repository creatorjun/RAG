from __future__ import annotations

from enterprise_rag.application.dto.claims import ClaimLedgerDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto
from enterprise_rag.application.dto.tasks import (
    FinalDocumentCandidateDto,
    TaskPlanDto,
    TaskPlanExecutionDto,
)
from enterprise_rag.application.use_cases.assemble_document import AssembleDocument
from enterprise_rag.application.use_cases.validate_final_document import (
    ValidateFinalDocument,
)
from enterprise_rag.domain.errors import revision_error


class BuildFinalDocumentCandidate:
    def __init__(
        self,
        assembler: AssembleDocument,
        validator: ValidateFinalDocument,
    ) -> None:
        self._assembler = assembler
        self._validator = validator

    def execute(
        self,
        title: str,
        plan: TaskPlanDto,
        ledger: ClaimLedgerDto,
        evidence: EvidenceBundleDto,
        execution: TaskPlanExecutionDto,
    ) -> FinalDocumentCandidateDto:
        if len(execution.outputs) != len(plan.tasks):
            raise revision_error("DOCUMENT_ASSEMBLY_FAILED")
        markdown = self._assembler.execute(
            title,
            plan,
            evidence,
            execution.outputs,
            execution.validations,
        )
        quality = self._validator.execute(
            markdown,
            plan,
            ledger,
            evidence,
            execution.outputs,
            execution.validations,
        )
        return FinalDocumentCandidateDto(markdown, quality)
