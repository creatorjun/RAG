from __future__ import annotations

from typing import Any, cast

from enterprise_rag.application.dto.web_research import (
    WebClaimAssessmentDto,
    WebResearchReportDto,
    WebResearchStatus,
    WebSourceDto,
    WebVerdict,
)
from enterprise_rag.application.ports.job_artifacts import JobArtifactRepositoryPort
from enterprise_rag.domain.errors import ApplicationError, revision_error

_PATH = "control/web-research.json"


class FilesystemWebResearchRepository:
    def __init__(self, artifacts: JobArtifactRepositoryPort) -> None:
        self._artifacts = artifacts

    async def save(self, job_id: str, report: WebResearchReportDto) -> str:
        value = self._value(job_id, report)
        try:
            return await self._artifacts.write_json_once(job_id, _PATH, value)
        except ApplicationError as error:
            if error.code != "JOB_ARTIFACT_ALREADY_EXISTS":
                raise
            if await self._artifacts.read_json(job_id, _PATH) != value:
                raise revision_error("FINAL_ARTIFACT_INVALID", {"job_id": job_id}) from error
            return _PATH

    async def load(self, job_id: str) -> WebResearchReportDto:
        value = await self._artifacts.read_json(job_id, _PATH)
        try:
            if value.get("schema_version") != 1 or value.get("job_id") != job_id:
                raise ValueError("invalid web research envelope")
            sources = tuple(self._source(item) for item in self._list(value["sources"]))
            assessments = tuple(
                self._assessment(item) for item in self._list(value["assessments"])
            )
            return WebResearchReportDto(
                status=self._status(value["status"]),
                sources=sources,
                assessments=assessments,
                error_codes=self._strings(value["error_codes"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise revision_error("FINAL_ARTIFACT_INVALID", {"job_id": job_id}) from error

    @staticmethod
    def _value(job_id: str, report: WebResearchReportDto) -> dict[str, object]:
        return {
            "schema_version": 1,
            "job_id": job_id,
            "status": report.status,
            "error_codes": list(report.error_codes),
            "sources": [
                {
                    "source_id": source.source_id,
                    "url": source.url,
                    "title": source.title,
                    "snippet": source.snippet,
                    "claim_ids": list(source.claim_ids),
                    "published_date": source.published_date,
                }
                for source in report.sources
            ],
            "assessments": [
                {
                    "claim_id": assessment.claim_id,
                    "query": assessment.query,
                    "verdict": assessment.verdict,
                    "source_ids": list(assessment.source_ids),
                    "note": assessment.note,
                }
                for assessment in report.assessments
            ],
        }

    @classmethod
    def _source(cls, value: Any) -> WebSourceDto:
        item = cls._mapping(value)
        return WebSourceDto(
            source_id=cls._string(item["source_id"]),
            url=cls._string(item["url"]),
            title=cls._string(item["title"]),
            snippet=cls._string(item["snippet"]),
            claim_ids=cls._strings(item["claim_ids"]),
            published_date=cls._optional_string(item["published_date"]),
        )

    @classmethod
    def _assessment(cls, value: Any) -> WebClaimAssessmentDto:
        item = cls._mapping(value)
        return WebClaimAssessmentDto(
            claim_id=cls._string(item["claim_id"]),
            query=cls._string(item["query"]),
            verdict=cls._verdict(item["verdict"]),
            source_ids=cls._strings(item["source_ids"]),
            note=cls._string(item["note"]),
        )

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("expected object")
        return value

    @staticmethod
    def _list(value: Any) -> list[Any]:
        if not isinstance(value, list):
            raise ValueError("expected list")
        return value

    @staticmethod
    def _string(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("expected string")
        return value

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        if value is not None and not isinstance(value, str):
            raise ValueError("expected optional string")
        return value

    @classmethod
    def _strings(cls, value: Any) -> tuple[str, ...]:
        return tuple(cls._string(item) for item in cls._list(value))

    @staticmethod
    def _status(value: Any) -> WebResearchStatus:
        if value not in {"DISABLED", "UNAVAILABLE", "SEARCHED", "REVIEWED"}:
            raise ValueError("invalid web research status")
        return cast(WebResearchStatus, value)

    @staticmethod
    def _verdict(value: Any) -> WebVerdict:
        if value not in {"SUPPORTED", "CONTRADICTED", "MIXED", "INCONCLUSIVE"}:
            raise ValueError("invalid web verdict")
        return cast(WebVerdict, value)
