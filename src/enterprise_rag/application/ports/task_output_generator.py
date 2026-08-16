from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.claims import ClaimDto
from enterprise_rag.application.dto.evidence import EvidenceItemDto
from enterprise_rag.application.dto.tasks import (
    TaskOutputDto,
    TaskPacketDto,
    TaskValidationReportDto,
)
from enterprise_rag.application.dto.web_research import WebResearchReportDto


class TaskOutputGeneratorPort(Protocol):
    async def generate(
        self,
        packet: TaskPacketDto,
        claims: tuple[ClaimDto, ...],
        evidence: tuple[EvidenceItemDto, ...],
        previous_validation: TaskValidationReportDto | None = None,
        web_research: WebResearchReportDto | None = None,
    ) -> TaskOutputDto:
        raise NotImplementedError
