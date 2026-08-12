from __future__ import annotations

from typing import Protocol


class DocumentJobLauncherPort(Protocol):
    async def launch(self, job_id: str) -> int:
        raise NotImplementedError
