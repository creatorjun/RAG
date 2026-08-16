from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.claims import ClaimDto
from enterprise_rag.application.dto.web_research import (
    WebClaimAssessmentDto,
    WebSourceDto,
)


class WebResearchReviewerPort(Protocol):
    async def review(
        self,
        claims: tuple[ClaimDto, ...],
        sources: tuple[WebSourceDto, ...],
        queries: dict[str, str],
    ) -> tuple[WebClaimAssessmentDto, ...]:
        raise NotImplementedError
