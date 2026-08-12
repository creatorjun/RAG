from typing import Protocol

from enterprise_rag.application.dto.model_catalog import ModelCatalogEntryDto


class ModelCatalogPort(Protocol):
    async def list_local(
        self,
        query: str,
        limit: int,
    ) -> tuple[ModelCatalogEntryDto, ...]:
        raise NotImplementedError

    async def search_remote(
        self,
        query: str,
        limit: int,
    ) -> tuple[ModelCatalogEntryDto, ...]:
        raise NotImplementedError

    async def inspect(
        self,
        model_id: str,
        revision: str,
        local_only: bool,
    ) -> ModelCatalogEntryDto:
        raise NotImplementedError
