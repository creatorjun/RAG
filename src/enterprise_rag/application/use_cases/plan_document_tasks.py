from __future__ import annotations

from enterprise_rag.application.dto.claims import ClaimLedgerDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto
from enterprise_rag.application.dto.tasks import TaskPlanDto
from enterprise_rag.application.ports.task_definition_generator import (
    TaskDefinitionGeneratorPort,
)
from enterprise_rag.application.use_cases.build_task_plan import BuildTaskPlan
from enterprise_rag.domain.errors import revision_error


class PlanDocumentTasks:
    def __init__(
        self,
        generator: TaskDefinitionGeneratorPort,
        builder: BuildTaskPlan,
    ) -> None:
        self._generator = generator
        self._builder = builder

    async def execute(
        self,
        ledger: ClaimLedgerDto,
        evidence: EvidenceBundleDto,
        instruction: str,
    ) -> TaskPlanDto:
        if not instruction.strip():
            raise revision_error("INVALID_INPUT", {"field": "instruction"})
        if set(ledger.reviewed_evidence_ids) != {
            item.evidence_id for item in evidence.items
        }:
            raise revision_error("COVERAGE_MATRIX_INCOMPLETE")
        definitions = await self._generator.generate(
            ledger,
            evidence,
            instruction.strip(),
        )
        return self._builder.execute(ledger, definitions)
