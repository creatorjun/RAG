from __future__ import annotations

from typing import Any

from enterprise_rag.application.dto.tasks import (
    FinalDocumentCandidateDto,
    FinalQualityReportDto,
)
from enterprise_rag.application.ports.job_artifacts import JobArtifactRepositoryPort
from enterprise_rag.domain.errors import ApplicationError, revision_error

_DRAFT_PATH = "derived/assembled-draft.md"
_VALIDATION_PATH = "control/final-validation.json"


class FilesystemFinalDocumentRepository:
    def __init__(self, artifacts: JobArtifactRepositoryPort) -> None:
        self._artifacts = artifacts

    async def save(
        self,
        job_id: str,
        candidate: FinalDocumentCandidateDto,
    ) -> tuple[str, str]:
        draft_path = await self._write_or_verify_draft(job_id, candidate.markdown)
        report_path = await self._write_or_verify_report(job_id, candidate.quality)
        return draft_path, report_path

    async def load(self, job_id: str) -> FinalDocumentCandidateDto:
        try:
            markdown = await self._artifacts.read_text(job_id, _DRAFT_PATH)
            value = await self._artifacts.read_json(job_id, _VALIDATION_PATH)
            if value.get("schema_version") != 1 or value.get("job_id") != job_id:
                raise ValueError("invalid final validation envelope")
            report = self._report(value)
            return FinalDocumentCandidateDto(markdown, report)
        except ApplicationError as error:
            if error.code == "JOB_ARTIFACT_NOT_FOUND":
                raise revision_error(
                    "FINAL_QUALITY_GATE_FAILED",
                    {"job_id": job_id},
                ) from error
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise revision_error(
                "FINAL_QUALITY_GATE_FAILED",
                {"job_id": job_id},
            ) from error

    async def _write_or_verify_draft(self, job_id: str, markdown: str) -> str:
        try:
            return await self._artifacts.write_text_once(job_id, _DRAFT_PATH, markdown)
        except ApplicationError as error:
            if error.code != "JOB_ARTIFACT_ALREADY_EXISTS":
                raise
            existing = await self._artifacts.read_text(job_id, _DRAFT_PATH)
            if existing != markdown:
                raise revision_error(
                    "FINAL_QUALITY_GATE_FAILED",
                    {"job_id": job_id},
                ) from error
            return _DRAFT_PATH

    async def _write_or_verify_report(
        self,
        job_id: str,
        report: FinalQualityReportDto,
    ) -> str:
        value: dict[str, object] = {
            "schema_version": 1,
            "job_id": job_id,
            "valid": report.valid,
            "error_codes": list(report.error_codes),
            "document_sha256": report.document_sha256,
            "source_document_count": report.source_document_count,
            "evidence_count": report.evidence_count,
            "claim_count": report.claim_count,
            "task_count": report.task_count,
            "validated_task_count": report.validated_task_count,
            "covered_claim_count": report.covered_claim_count,
            "covered_evidence_count": report.covered_evidence_count,
        }
        try:
            return await self._artifacts.write_json_once(job_id, _VALIDATION_PATH, value)
        except ApplicationError as error:
            if error.code != "JOB_ARTIFACT_ALREADY_EXISTS":
                raise
            existing = await self._artifacts.read_json(job_id, _VALIDATION_PATH)
            if existing != value:
                raise revision_error(
                    "FINAL_QUALITY_GATE_FAILED",
                    {"job_id": job_id},
                ) from error
            return _VALIDATION_PATH

    @classmethod
    def _report(cls, value: dict[str, Any]) -> FinalQualityReportDto:
        valid = value["valid"]
        if not isinstance(valid, bool):
            raise ValueError("invalid final quality status")
        return FinalQualityReportDto(
            valid=valid,
            error_codes=cls._strings(value["error_codes"]),
            document_sha256=cls._string(value["document_sha256"]),
            source_document_count=cls._integer(value["source_document_count"]),
            evidence_count=cls._integer(value["evidence_count"]),
            claim_count=cls._integer(value["claim_count"]),
            task_count=cls._integer(value["task_count"]),
            validated_task_count=cls._integer(value["validated_task_count"]),
            covered_claim_count=cls._integer(value["covered_claim_count"]),
            covered_evidence_count=cls._integer(value["covered_evidence_count"]),
        )

    @staticmethod
    def _integer(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("expected integer")
        return int(value)

    @staticmethod
    def _string(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("expected string")
        return value

    @classmethod
    def _strings(cls, value: Any) -> tuple[str, ...]:
        if not isinstance(value, list):
            raise ValueError("expected list")
        return tuple(cls._string(item) for item in value)
