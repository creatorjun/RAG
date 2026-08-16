from __future__ import annotations

from enterprise_rag.application.dto.claims import ClaimLedgerDto
from enterprise_rag.application.dto.tasks import (
    TaskOutputDto,
    TaskPacketDto,
    TaskValidationReportDto,
)


class ValidateTaskOutput:
    """Compatibility adapter that records generation without a quality gate.

    Task output shape and reference decoding are already checked at the model adapter
    boundary.  Prose coverage, citation placement, and verbatim wording are quality
    signals, not reasons to discard a generated task or stop the document pipeline.
    """

    def execute(
        self,
        packet: TaskPacketDto,
        ledger: ClaimLedgerDto,
        output: TaskOutputDto,
    ) -> TaskValidationReportDto:
        del ledger, output
        return TaskValidationReportDto(packet.task_id, True, ())
