from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.claims import ClaimLedgerDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto
from enterprise_rag.application.dto.tasks import TaskDefinitionDto


class TaskDefinitionGeneratorPort(Protocol):
    async def generate(
        self,
        ledger: ClaimLedgerDto,
        evidence: EvidenceBundleDto,
        instruction: str,
    ) -> tuple[TaskDefinitionDto, ...]:
        raise NotImplementedError
