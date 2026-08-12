from __future__ import annotations

from enterprise_rag.application.dto.claims import ClaimLedgerDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto
from enterprise_rag.application.dto.tasks import (
    TaskAttemptResultDto,
    TaskPacketDto,
    TaskValidationReportDto,
)
from enterprise_rag.application.ports.task_output_generator import (
    TaskOutputGeneratorPort,
)
from enterprise_rag.application.ports.task_result_repository import (
    TaskResultRepositoryPort,
)
from enterprise_rag.application.use_cases.validate_task_output import ValidateTaskOutput
from enterprise_rag.domain.errors import revision_error


class ExecuteTaskAttempt:
    def __init__(
        self,
        generator: TaskOutputGeneratorPort,
        results: TaskResultRepositoryPort,
        validator: ValidateTaskOutput,
    ) -> None:
        self._generator = generator
        self._results = results
        self._validator = validator

    async def execute(
        self,
        job_id: str,
        packet: TaskPacketDto,
        ledger: ClaimLedgerDto,
        evidence: EvidenceBundleDto,
        attempt: int,
        previous_validation: TaskValidationReportDto | None = None,
    ) -> TaskAttemptResultDto:
        if not 1 <= attempt <= 3:
            raise revision_error("TASK_OUTPUT_INVALID", {"task_id": packet.task_id})
        if attempt == 1 and previous_validation is not None:
            raise revision_error("TASK_OUTPUT_INVALID", {"task_id": packet.task_id})
        if attempt > 1 and (
            previous_validation is None
            or previous_validation.valid
            or previous_validation.task_id != packet.task_id
        ):
            raise revision_error("TASK_OUTPUT_INVALID", {"task_id": packet.task_id})
        claim_by_id = {claim.claim_id: claim for claim in ledger.claims}
        evidence_by_id = {item.evidence_id: item for item in evidence.items}
        visible_claim_ids = packet.owned_claim_ids + packet.context_claim_ids
        try:
            claims = tuple(claim_by_id[claim_id] for claim_id in visible_claim_ids)
            evidence_items = tuple(
                evidence_by_id[evidence_id]
                for evidence_id in packet.allowed_evidence_ids
            )
        except KeyError as error:
            raise revision_error(
                "TASK_PLAN_INVALID",
                {"task_id": packet.task_id},
            ) from error
        output = await self._generator.generate(
            packet,
            claims,
            evidence_items,
            previous_validation,
        )
        await self._results.save_output(job_id, attempt, output)
        validation = self._validator.execute(packet, ledger, output)
        await self._results.save_validation(job_id, attempt, validation)
        return TaskAttemptResultDto(attempt, output, validation)
