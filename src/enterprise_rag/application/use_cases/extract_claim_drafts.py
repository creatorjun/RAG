from __future__ import annotations

from collections.abc import Callable

from enterprise_rag.application.dto.claims import ClaimDraftDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto
from enterprise_rag.application.ports.claim_draft_generator import ClaimDraftGeneratorPort
from enterprise_rag.domain.errors import revision_error

ClaimExtractionCallback = Callable[[int, int, str], None]


class ExtractClaimDrafts:
    def __init__(self, generator: ClaimDraftGeneratorPort) -> None:
        self._generator = generator

    async def execute(
        self,
        evidence: EvidenceBundleDto,
        instruction: str,
        progress: ClaimExtractionCallback | None = None,
    ) -> tuple[ClaimDraftDto, ...]:
        if not instruction.strip():
            raise revision_error("INVALID_INPUT", {"field": "instruction"})
        drafts: list[ClaimDraftDto] = []
        total = len(evidence.items)
        for index, item in enumerate(evidence.items, start=1):
            generated = await self._generator.generate(item, instruction.strip())
            if not generated or any(
                draft.evidence_ids != (item.evidence_id,) for draft in generated
            ):
                raise revision_error(
                    "CLAIM_LEDGER_INVALID",
                    {"evidence_id": item.evidence_id},
                )
            drafts.extend(generated)
            if progress is not None:
                progress(index, total, item.evidence_id)
        draft_ids = [draft.draft_id for draft in drafts]
        if len(draft_ids) != len(set(draft_ids)):
            raise revision_error("CLAIM_LEDGER_INVALID")
        return tuple(drafts)
