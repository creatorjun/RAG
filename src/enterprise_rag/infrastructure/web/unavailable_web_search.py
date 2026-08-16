from __future__ import annotations

from enterprise_rag.application.dto.web_research import WebSearchResultDto
from enterprise_rag.domain.errors import revision_error


class UnavailableWebSearch:
    async def search(
        self,
        query: str,
        maximum_results: int,
    ) -> tuple[WebSearchResultDto, ...]:
        del query, maximum_results
        raise revision_error("WEB_SEARCH_UNAVAILABLE")
