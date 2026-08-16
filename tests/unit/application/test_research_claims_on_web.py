from __future__ import annotations

import asyncio
import json
import unittest

from enterprise_rag.application.dto.claims import ClaimDto, ClaimLedgerDto
from enterprise_rag.application.dto.web_research import (
    WebClaimAssessmentDto,
    WebSearchResultDto,
)
from enterprise_rag.application.use_cases.research_claims_on_web import ResearchClaimsOnWeb
from enterprise_rag.domain.claims import ClaimKind
from enterprise_rag.infrastructure.web.tavily_web_search import TavilyWebSearch


def _ledger() -> ClaimLedgerDto:
    evidence_id = "evidence:sha256:" + "a" * 64
    claims = (
        ClaimDto(
            "claim:sha256:" + "b" * 64,
            ClaimKind.FACT,
            "제품 3.2 버전은 2026년에 지원된다.",
            (evidence_id,),
        ),
        ClaimDto(
            "claim:sha256:" + "c" * 64,
            ClaimKind.WARNING,
            "기본 모드는 LEGACY가 아니다.",
            (evidence_id,),
        ),
    )
    return ClaimLedgerDto(claims, (), (evidence_id,))


class _Search:
    async def search(self, query: str, maximum_results: int):
        del maximum_results
        suffix = "version" if "3.2" in query else "mode"
        return (
            WebSearchResultDto(
                f"https://docs.example.com/{suffix}",
                f"Official {suffix}",
                f"Independent evidence for {query}",
            ),
        )


class _Reviewer:
    async def review(self, claims, sources, queries):
        return tuple(
            WebClaimAssessmentDto(
                claim.claim_id,
                queries[claim.claim_id],
                "SUPPORTED",
                tuple(
                    source.source_id
                    for source in sources
                    if claim.claim_id in source.claim_ids
                ),
                "독립 문서가 같은 조건을 직접 확인합니다.",
            )
            for claim in claims
        )


class _FailingSearch:
    async def search(self, query: str, maximum_results: int):
        del query, maximum_results
        raise OSError("network down")


class _RecordingSearch(_Search):
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str, maximum_results: int):
        self.queries.append(query)
        return await super().search(query, maximum_results)


class ResearchClaimsOnWebTest(unittest.TestCase):
    def test_researches_selected_claims_and_keeps_reviewed_sources_separate(self) -> None:
        report = asyncio.run(ResearchClaimsOnWeb(_Search(), _Reviewer()).execute(_ledger()))

        self.assertEqual(report.status, "REVIEWED")
        self.assertEqual(len(report.assessments), 2)
        self.assertEqual({item.verdict for item in report.assessments}, {"SUPPORTED"})
        self.assertEqual(len(report.sources), 2)

    def test_search_failure_is_an_observation_not_an_exception(self) -> None:
        report = asyncio.run(
            ResearchClaimsOnWeb(_FailingSearch(), _Reviewer()).execute(_ledger())
        )

        self.assertEqual(report.status, "UNAVAILABLE")
        self.assertEqual(report.error_codes, ("WEB_SEARCH_UNAVAILABLE",))
        self.assertTrue(all(item.verdict == "INCONCLUSIVE" for item in report.assessments))

    def test_sensitive_claim_text_is_never_sent_as_a_search_query(self) -> None:
        evidence_id = "evidence:sha256:" + "a" * 64
        ledger = ClaimLedgerDto(
            (
                ClaimDto(
                    "claim:sha256:" + "d" * 64,
                    ClaimKind.FACT,
                    "DEMO_ACCESS_TOKEN=secret-value를 사용한다.",
                    (evidence_id,),
                ),
            ),
            (),
            (evidence_id,),
        )
        search = _RecordingSearch()

        report = asyncio.run(ResearchClaimsOnWeb(search, _Reviewer()).execute(ledger))

        self.assertEqual(search.queries, [])
        self.assertEqual(report.error_codes, ("NO_WEB_CLAIMS",))

    def test_tavily_adapter_uses_domain_allowlist_and_parses_https_results(self) -> None:
        captured: dict[str, object] = {}

        def transport(request, timeout):
            captured["payload"] = json.loads(request.data)
            captured["timeout"] = timeout
            return json.dumps(
                {
                    "results": [
                        {
                            "url": "https://docs.example.com/current",
                            "title": "Current support",
                            "content": "Version 3.2 remains supported.",
                        },
                        {
                            "url": "http://unsafe.example.com/result",
                            "title": "Ignored",
                            "content": "Non-HTTPS result",
                        },
                    ]
                }
            ).encode()

        search = TavilyWebSearch(
            "secret-key",
            ("docs.example.com",),
            transport=transport,
        )
        results = asyncio.run(search.search("product 3.2 support", 3))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://docs.example.com/current")
        self.assertEqual(captured["payload"]["include_domains"], ["docs.example.com"])


if __name__ == "__main__":
    unittest.main()
