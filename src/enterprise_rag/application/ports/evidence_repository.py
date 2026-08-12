from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.evidence import EvidenceBundleDto


class EvidenceRepositoryPort(Protocol):
    async def save(self, job_id: str, bundle: EvidenceBundleDto) -> str:
        raise NotImplementedError

    async def load(self, job_id: str) -> EvidenceBundleDto:
        raise NotImplementedError
