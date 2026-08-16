from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from enterprise_rag.application.dto.web_research import WebSearchResultDto
from enterprise_rag.domain.errors import revision_error

_TAVILY_ENDPOINT = "https://api.tavily.com/search"
Transport = Callable[[urllib.request.Request, float], bytes]


class TavilyWebSearch:
    def __init__(
        self,
        api_key: str,
        allowed_domains: tuple[str, ...] = (),
        timeout_seconds: float = 20.0,
        transport: Transport | None = None,
    ) -> None:
        if not api_key.strip() or timeout_seconds <= 0:
            raise ValueError("Tavily search configuration is invalid")
        self._api_key = api_key
        self._allowed_domains = tuple(
            domain.strip().casefold() for domain in allowed_domains if domain.strip()
        )
        if any(
            "*" in domain or "/" in domain or ":" in domain
            for domain in self._allowed_domains
        ):
            raise ValueError("Tavily allowed domain is invalid")
        self._timeout_seconds = timeout_seconds
        self._transport = transport or self._send

    async def search(
        self,
        query: str,
        maximum_results: int,
    ) -> tuple[WebSearchResultDto, ...]:
        if not query.strip() or not 1 <= maximum_results <= 10:
            raise ValueError("web search request is invalid")
        return await asyncio.to_thread(self._search, query.strip(), maximum_results)

    def _search(
        self,
        query: str,
        maximum_results: int,
    ) -> tuple[WebSearchResultDto, ...]:
        payload: dict[str, object] = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": maximum_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        if self._allowed_domains:
            payload["include_domains"] = list(self._allowed_domains)
        request = urllib.request.Request(
            _TAVILY_ENDPOINT,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            value = json.loads(self._transport(request, self._timeout_seconds))
            if not isinstance(value, dict) or not isinstance(value.get("results"), list):
                raise ValueError("invalid Tavily response")
            results: list[WebSearchResultDto] = []
            for raw in value["results"]:
                if not isinstance(raw, dict):
                    continue
                result = self._result(raw)
                if result is not None and self._domain_allowed(result.url):
                    results.append(result)
            return tuple(results[:maximum_results])
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            raise revision_error("WEB_SEARCH_UNAVAILABLE") from error

    @staticmethod
    def _result(value: dict[str, Any]) -> WebSearchResultDto | None:
        url = value.get("url")
        title = value.get("title")
        content = value.get("content")
        published_date = value.get("published_date")
        if not isinstance(url, str) or not url.startswith("https://"):
            return None
        if not isinstance(title, str) or not title.strip():
            return None
        if not isinstance(content, str) or not content.strip():
            return None
        return WebSearchResultDto(
            url=url,
            title=title.strip()[:500],
            snippet=content.strip()[:4_000],
            published_date=(
                published_date[:100] if isinstance(published_date, str) else None
            ),
        )

    def _domain_allowed(self, url: str) -> bool:
        if not self._allowed_domains:
            return True
        hostname = (urllib.parse.urlparse(url).hostname or "").casefold()
        return any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in self._allowed_domains
        )

    @staticmethod
    def _send(request: urllib.request.Request, timeout_seconds: float) -> bytes:
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return bytes(response.read())
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            raise OSError("Tavily request failed") from error
