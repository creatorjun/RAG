from collections.abc import Callable
from typing import Protocol

from enterprise_rag.application.dto.model_catalog import ModelCatalogEntryDto
from enterprise_rag.application.dto.model_download import ModelDownloadProgressDto

ModelDownloadProgressCallback = Callable[[ModelDownloadProgressDto], None]


class ModelDownloadPort(Protocol):
    async def download(
        self,
        download_id: str,
        model_id: str,
        revision: str,
        progress: ModelDownloadProgressCallback,
    ) -> ModelCatalogEntryDto:
        raise NotImplementedError

    async def cancel(self, download_id: str) -> bool:
        raise NotImplementedError
