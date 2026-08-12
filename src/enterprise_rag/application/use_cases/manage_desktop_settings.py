from __future__ import annotations

from enterprise_rag.application.dto.desktop_settings import DesktopSettingsDto
from enterprise_rag.application.ports.desktop_settings_repository import (
    DesktopSettingsRepositoryPort,
)
from enterprise_rag.domain.errors import revision_error


class GetDesktopSettings:
    def __init__(self, settings: DesktopSettingsRepositoryPort) -> None:
        self._settings = settings

    async def execute(self) -> DesktopSettingsDto:
        return await self._settings.load()


class UpdateDesktopSettings:
    def __init__(self, settings: DesktopSettingsRepositoryPort) -> None:
        self._settings = settings

    async def execute(
        self,
        expected_revision: int,
        desired: DesktopSettingsDto,
    ) -> DesktopSettingsDto:
        if desired.settings_revision != expected_revision:
            raise revision_error("SETTINGS_REVISION_CONFLICT")
        return await self._settings.save(expected_revision, desired)
