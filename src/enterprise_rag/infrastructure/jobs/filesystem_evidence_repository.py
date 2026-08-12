from __future__ import annotations

from dataclasses import asdict
from typing import Any

from enterprise_rag.application.dto.evidence import EvidenceBundleDto, EvidenceItemDto
from enterprise_rag.application.ports.job_artifacts import JobArtifactRepositoryPort
from enterprise_rag.domain.errors import revision_error

_EVIDENCE_PATH = "evidence/index.json"


class FilesystemEvidenceRepository:
    def __init__(self, artifacts: JobArtifactRepositoryPort) -> None:
        self._artifacts = artifacts

    async def save(self, job_id: str, bundle: EvidenceBundleDto) -> str:
        return await self._artifacts.write_json_once(
            job_id,
            _EVIDENCE_PATH,
            {
                "schema_version": 1,
                "job_id": job_id,
                "source_document_count": bundle.source_document_count,
                "source_structure_count": bundle.source_structure_count,
                "items": [asdict(item) for item in bundle.items],
            },
        )

    async def load(self, job_id: str) -> EvidenceBundleDto:
        value = await self._artifacts.read_json(job_id, _EVIDENCE_PATH)
        try:
            if value.get("schema_version") != 1 or value.get("job_id") != job_id:
                raise ValueError("invalid evidence manifest")
            raw_items = value["items"]
            if not isinstance(raw_items, list):
                raise ValueError("invalid evidence items")
            items = tuple(self._item(item) for item in raw_items)
            return EvidenceBundleDto(
                items=items,
                source_document_count=self._integer(value["source_document_count"]),
                source_structure_count=self._integer(value["source_structure_count"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise revision_error("EVIDENCE_COVERAGE_FAILED", {"job_id": job_id}) from error

    @staticmethod
    def _item(value: Any) -> EvidenceItemDto:
        if not isinstance(value, dict):
            raise ValueError("invalid evidence item")
        return EvidenceItemDto(
            evidence_id=str(value["evidence_id"]),
            chunk_id=str(value["chunk_id"]),
            revision_id=str(value["revision_id"]),
            relative_path=str(value["relative_path"]),
            source_sha256=str(value["source_sha256"]),
            ordinal=FilesystemEvidenceRepository._integer(value["ordinal"]),
            start_char=FilesystemEvidenceRepository._integer(value["start_char"]),
            end_char=FilesystemEvidenceRepository._integer(value["end_char"]),
            content_sha256=str(value["content_sha256"]),
            text=str(value["text"]),
        )

    @staticmethod
    def _integer(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("expected integer")
        return int(value)
