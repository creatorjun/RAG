from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

WebVerdict = Literal["SUPPORTED", "CONTRADICTED", "MIXED", "INCONCLUSIVE"]
WebResearchStatus = Literal["DISABLED", "UNAVAILABLE", "SEARCHED", "REVIEWED"]


@dataclass(frozen=True, slots=True)
class WebSearchResultDto:
    url: str
    title: str
    snippet: str
    published_date: str | None = None

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or not parsed.netloc or not self.title.strip():
            raise ValueError("invalid web search result")
        if not self.snippet.strip():
            raise ValueError("web search result requires content")


@dataclass(frozen=True, slots=True)
class WebSourceDto:
    source_id: str
    url: str
    title: str
    snippet: str
    claim_ids: tuple[str, ...]
    published_date: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id.startswith("web:sha256:") or len(self.source_id) != 75:
            raise ValueError("invalid web source ID")
        if urlparse(self.url).scheme != "https" or not self.claim_ids:
            raise ValueError("invalid web source")
        if len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("duplicate web source claim")


@dataclass(frozen=True, slots=True)
class WebClaimAssessmentDto:
    claim_id: str
    query: str
    verdict: WebVerdict
    source_ids: tuple[str, ...]
    note: str

    def __post_init__(self) -> None:
        if not self.claim_id or not self.query.strip() or not self.note.strip():
            raise ValueError("invalid web claim assessment")
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("duplicate web assessment source")


@dataclass(frozen=True, slots=True)
class WebResearchReportDto:
    status: WebResearchStatus
    sources: tuple[WebSourceDto, ...]
    assessments: tuple[WebClaimAssessmentDto, ...]
    error_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        source_ids = {source.source_id for source in self.sources}
        if len(source_ids) != len(self.sources):
            raise ValueError("duplicate web research source")
        if any(set(item.source_ids) - source_ids for item in self.assessments):
            raise ValueError("web assessment references unknown source")
        claim_ids = [item.claim_id for item in self.assessments]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("duplicate web claim assessment")

    def for_claims(self, claim_ids: tuple[str, ...]) -> WebResearchReportDto:
        selected = set(claim_ids)
        assessments = tuple(
            assessment
            for assessment in self.assessments
            if assessment.claim_id in selected
        )
        source_ids = {
            source_id for assessment in assessments for source_id in assessment.source_ids
        }
        sources = tuple(
            source for source in self.sources if source.source_id in source_ids
        )
        return WebResearchReportDto(self.status, sources, assessments, self.error_codes)
