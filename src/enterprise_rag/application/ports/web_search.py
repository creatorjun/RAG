from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.web_research import WebSearchResultDto


class WebSearchPort(Protocol):
    async def search(
        self,
        query: str,
        maximum_results: int,
    ) -> tuple[WebSearchResultDto, ...]:
        raise NotImplementedError
