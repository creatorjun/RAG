from __future__ import annotations

from typing import Protocol

from enterprise_rag.application.dto.desktop_settings import DesktopSettingsDto


class DesktopSettingsRepositoryPort(Protocol):
    async def load(self) -> DesktopSettingsDto:
        raise NotImplementedError

    async def save(
        self,
        expected_revision: int,
        settings: DesktopSettingsDto,
    ) -> DesktopSettingsDto:
        raise NotImplementedError
