from __future__ import annotations

import re

from enterprise_rag.application.dto.model_catalog import (
    ModelCatalogEntryDto,
    ModelCompatibility,
)
from enterprise_rag.application.ports.model_download import (
    ModelDownloadPort,
    ModelDownloadProgressCallback,
)
from enterprise_rag.application.use_cases.model_catalog import InspectModelSelection
from enterprise_rag.domain.errors import revision_error

_DOWNLOAD_ID = re.compile(r"^download-[0-9a-f]{32}$")


class DownloadModel:
    def __init__(
        self,
        selection: InspectModelSelection,
        downloads: ModelDownloadPort,
    ) -> None:
        self._selection = selection
        self._downloads = downloads

    async def execute(
        self,
        download_id: str,
        model_id: str,
        revision: str,
        progress: ModelDownloadProgressCallback,
    ) -> ModelCatalogEntryDto:
        if _DOWNLOAD_ID.fullmatch(download_id) is None:
            raise revision_error("INVALID_INPUT", {"field": "download_id"})
        entry = await self._selection.execute(model_id, revision, False)
        if entry.compatibility in {
            ModelCompatibility.UNSUPPORTED,
            ModelCompatibility.TOO_LARGE,
        }:
            raise revision_error(
                "MODEL_INCOMPATIBLE",
                {
                    "model_id": entry.model_id,
                    "compatibility": entry.compatibility.value,
                },
            )
        return await self._downloads.download(
            download_id,
            entry.model_id,
            entry.revision,
            progress,
        )


class CancelModelDownload:
    def __init__(self, downloads: ModelDownloadPort) -> None:
        self._downloads = downloads

    async def execute(self, download_id: str) -> bool:
        if _DOWNLOAD_ID.fullmatch(download_id) is None:
            raise revision_error("INVALID_INPUT", {"field": "download_id"})
        return await self._downloads.cancel(download_id)
