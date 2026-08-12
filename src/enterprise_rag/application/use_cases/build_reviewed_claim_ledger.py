from __future__ import annotations

from enterprise_rag.application.dto.claims import ClaimDraftDto, ClaimLedgerDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto
from enterprise_rag.application.ports.claim_relation_generator import (
    ClaimRelationGeneratorPort,
)
from enterprise_rag.application.use_cases.build_claim_ledger import BuildClaimLedger
from enterprise_rag.domain.errors import revision_error


class BuildReviewedClaimLedger:
    def __init__(
        self,
        relation_generator: ClaimRelationGeneratorPort,
        builder: BuildClaimLedger,
    ) -> None:
        self._relation_generator = relation_generator
        self._builder = builder

    async def execute(
        self,
        evidence: EvidenceBundleDto,
        drafts: tuple[ClaimDraftDto, ...],
        instruction: str,
    ) -> ClaimLedgerDto:
        if not instruction.strip() or not drafts:
            raise revision_error("CLAIM_LEDGER_INVALID")
        relations = await self._relation_generator.generate(
            drafts,
            evidence,
            instruction.strip(),
        )
        return self._builder.execute(evidence, drafts, relations)
