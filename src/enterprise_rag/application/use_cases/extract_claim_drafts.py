from __future__ import annotations

from collections.abc import Callable

from enterprise_rag.application.dto.claims import ClaimDraftDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto
from enterprise_rag.application.ports.claim_draft_generator import ClaimDraftGeneratorPort
from enterprise_rag.application.ports.claim_draft_repository import (
    ClaimDraftRepositoryPort,
)
from enterprise_rag.domain.errors import revision_error

ClaimExtractionCallback = Callable[[int, int, str], None]


class ExtractClaimDrafts:
    def __init__(
        self,
        generator: ClaimDraftGeneratorPort,
        repository: ClaimDraftRepositoryPort | None = None,
    ) -> None:
        self._generator = generator
        self._repository = repository

    async def execute(
        self,
        evidence: EvidenceBundleDto,
        instruction: str,
        progress: ClaimExtractionCallback | None = None,
        job_id: str | None = None,
    ) -> tuple[ClaimDraftDto, ...]:
        if not instruction.strip():
            raise revision_error("INVALID_INPUT", {"field": "instruction"})
        drafts: list[ClaimDraftDto] = []
        total = len(evidence.items)
        for index, item in enumerate(evidence.items, start=1):
            generated = None
            if self._repository is not None and job_id is not None:
                generated = await self._repository.load(job_id, item.evidence_id)
            if generated is None:
                generated = await self._generator.generate(item, instruction.strip())
                if self._repository is not None and job_id is not None:
                    await self._repository.save(job_id, item.evidence_id, generated)
            if any(
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
        if not drafts or len(draft_ids) != len(set(draft_ids)):
            raise revision_error("CLAIM_LEDGER_INVALID")
        return tuple(drafts)
