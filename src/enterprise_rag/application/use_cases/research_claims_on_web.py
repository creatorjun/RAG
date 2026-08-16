from __future__ import annotations

import asyncio
import hashlib
import re

from enterprise_rag.application.dto.claims import ClaimDto, ClaimLedgerDto
from enterprise_rag.application.dto.web_research import (
    WebClaimAssessmentDto,
    WebResearchReportDto,
    WebSearchResultDto,
    WebSourceDto,
)
from enterprise_rag.application.ports.web_research_reviewer import (
    WebResearchReviewerPort,
)
from enterprise_rag.application.ports.web_search import WebSearchPort
from enterprise_rag.domain.claims import ClaimKind, ClaimRelationType

_FRESHNESS_SIGNAL = re.compile(
    r"(?i)(?:\b20\d{2}\b|\bv?\d+(?:\.\d+){1,3}\b|"
    r"지원|버전|최신|현재|deprecated|deprecat|support|require|default|legacy)"
)
_SENSITIVE_QUERY = re.compile(
    r"(?i)(?:\b[A-Z0-9_.-]*(?:token|password|passwd|secret|api[_-]?key|"
    r"private[_-]?key)[A-Z0-9_.-]*\s*[:=]"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b|"
    r"\b[0-9a-f]{32,}\b|\b[^\s@]+@[^\s@]+\.[^\s@]+\b|"
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b|\b[^\s]+\.(?:internal|local)\b)"
)


class ResearchClaimsOnWeb:
    """Select externally checkable Claims and review independent search evidence.

    Search or review failures are returned as observations.  They never raise a quality
    gate that can stop document creation.
    """

    def __init__(
        self,
        search: WebSearchPort,
        reviewer: WebResearchReviewerPort,
        maximum_claims: int = 8,
        maximum_results_per_claim: int = 3,
    ) -> None:
        self._search = search
        self._reviewer = reviewer
        self._maximum_claims = maximum_claims
        self._maximum_results = maximum_results_per_claim

    async def execute(self, ledger: ClaimLedgerDto) -> WebResearchReportDto:
        candidates = self._select_claims(ledger, self._maximum_claims * 2)
        query_pairs = [
            (claim, query)
            for claim in candidates
            if (query := self._query(claim)) is not None
        ][: self._maximum_claims]
        claims = tuple(claim for claim, _ in query_pairs)
        if not claims:
            return WebResearchReportDto("UNAVAILABLE", (), (), ("NO_WEB_CLAIMS",))
        queries = {claim.claim_id: query for claim, query in query_pairs}
        responses = await asyncio.gather(
            *(
                self._search_safe(queries[claim.claim_id])
                for claim in claims
            )
        )
        sources = self._sources(claims, responses)
        if not sources:
            assessments = tuple(
                WebClaimAssessmentDto(
                    claim.claim_id,
                    queries[claim.claim_id],
                    "INCONCLUSIVE",
                    (),
                    "독립 웹 근거를 가져오지 못했습니다.",
                )
                for claim in claims
            )
            return WebResearchReportDto(
                "UNAVAILABLE",
                (),
                assessments,
                ("WEB_SEARCH_UNAVAILABLE",),
            )
        try:
            assessments = await self._reviewer.review(claims, sources, queries)
            return WebResearchReportDto("REVIEWED", sources, assessments)
        except Exception:
            assessments = tuple(
                WebClaimAssessmentDto(
                    claim.claim_id,
                    queries[claim.claim_id],
                    "INCONCLUSIVE",
                    tuple(
                        source.source_id
                        for source in sources
                        if claim.claim_id in source.claim_ids
                    ),
                    "웹 검색 결과를 확보했지만 독립 판정을 완료하지 못했습니다.",
                )
                for claim in claims
            )
            return WebResearchReportDto(
                "SEARCHED",
                sources,
                assessments,
                ("WEB_REVIEW_UNAVAILABLE",),
            )

    async def _search_safe(self, query: str) -> tuple[WebSearchResultDto, ...]:
        try:
            return await self._search.search(query, self._maximum_results)
        except Exception:
            return ()

    @staticmethod
    def disabled() -> WebResearchReportDto:
        return WebResearchReportDto("DISABLED", (), ())

    @staticmethod
    def _select_claims(
        ledger: ClaimLedgerDto,
        maximum_claims: int,
    ) -> tuple[ClaimDto, ...]:
        conflict_claims = {
            claim_id
            for relation in ledger.relations
            if relation.relation is ClaimRelationType.CONFLICT
            for claim_id in (relation.left_claim_id, relation.right_claim_id)
        }

        def priority(claim: ClaimDto) -> tuple[int, int, str]:
            score = 0
            if claim.claim_id in conflict_claims:
                score += 100
            if _FRESHNESS_SIGNAL.search(claim.statement):
                score += 40
            if claim.kind in {ClaimKind.WARNING, ClaimKind.PREREQUISITE, ClaimKind.FACT}:
                score += 20
            if claim.commands:
                score += 5
            return (-score, -len(claim.statement), claim.claim_id)

        return tuple(sorted(ledger.claims, key=priority)[:maximum_claims])

    @staticmethod
    def _query(claim: ClaimDto) -> str | None:
        statement = claim.statement.strip()
        if not statement or _SENSITIVE_QUERY.search(statement):
            return None
        without_urls = re.sub(r"https?://\S+", "", statement).strip()
        return without_urls[:500] or None

    @staticmethod
    def _sources(
        claims: tuple[ClaimDto, ...],
        responses: list[tuple[WebSearchResultDto, ...]],
    ) -> tuple[WebSourceDto, ...]:
        by_url: dict[str, tuple[WebSearchResultDto, list[str]]] = {}
        for claim, results in zip(claims, responses, strict=True):
            for result in results:
                existing = by_url.get(result.url)
                if existing is None:
                    by_url[result.url] = (result, [claim.claim_id])
                elif claim.claim_id not in existing[1]:
                    existing[1].append(claim.claim_id)
        return tuple(
            WebSourceDto(
                source_id="web:sha256:"
                + hashlib.sha256(url.encode("utf-8")).hexdigest(),
                url=url,
                title=result.title.strip(),
                snippet=result.snippet.strip()[:4_000],
                claim_ids=tuple(claim_ids),
                published_date=result.published_date,
            )
            for url, (result, claim_ids) in sorted(by_url.items())
        )
