from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.web_research import WebResearchReportDto


class WebResearchRepositoryPort(Protocol):
    async def save(self, job_id: str, report: WebResearchReportDto) -> str:
        raise NotImplementedError

    async def load(self, job_id: str) -> WebResearchReportDto:
        raise NotImplementedError
