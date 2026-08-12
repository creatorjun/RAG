from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from enterprise_rag.application.dto.jobs import CreateDocumentJobDto
from enterprise_rag.domain.jobs import DocumentJob


class JobArtifactRepositoryPort(Protocol):
    async def initialize(
        self,
        job: DocumentJob,
        definition: CreateDocumentJobDto,
    ) -> None:
        raise NotImplementedError

    async def write_json_once(
        self,
        job_id: str,
        relative_path: str,
        value: Mapping[str, object],
    ) -> str:
        raise NotImplementedError

    async def read_json(self, job_id: str, relative_path: str) -> dict[str, Any]:
        raise NotImplementedError

    async def write_text_once(
        self,
        job_id: str,
        relative_path: str,
        value: str,
    ) -> str:
        raise NotImplementedError

    async def read_text(self, job_id: str, relative_path: str) -> str:
        raise NotImplementedError
