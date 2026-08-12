from __future__ import annotations

import re

from enterprise_rag.application.dto.model_catalog import (
    ModelCatalogDto,
    ModelCatalogEntryDto,
    ModelCompatibility,
)
from enterprise_rag.application.ports.model_catalog import ModelCatalogPort
from enterprise_rag.domain.errors import revision_error


class BrowseLocalModels:
    def __init__(self, catalog: ModelCatalogPort) -> None:
        self._catalog = catalog

    async def execute(self, query: str = "", limit: int = 100) -> ModelCatalogDto:
        normalized, bounded = _request(query, limit)
        entries = await self._catalog.list_local(normalized, bounded)
        return ModelCatalogDto(normalized, False, entries)


class SearchHuggingFaceModels:
    def __init__(self, catalog: ModelCatalogPort) -> None:
        self._catalog = catalog

    async def execute(self, query: str, limit: int = 25) -> ModelCatalogDto:
        normalized, bounded = _request(query, limit)
        entries = await self._catalog.search_remote(normalized, bounded)
        return ModelCatalogDto(normalized, True, entries)


class InspectModelSelection:
    def __init__(self, catalog: ModelCatalogPort) -> None:
        self._catalog = catalog

    async def execute(
        self,
        model_id: str,
        revision: str,
        offline_mode: bool,
    ) -> ModelCatalogEntryDto:
        normalized_id = model_id.strip()
        normalized_revision = revision.strip().lower()
        if (
            re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}/"
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}",
                normalized_id,
            )
            is None
            or re.fullmatch(r"[0-9a-f]{40}", normalized_revision) is None
        ):
            raise revision_error("MODEL_SELECTION_INVALID")
        try:
            return await self._catalog.inspect(
                normalized_id,
                normalized_revision,
                offline_mode,
            )
        except ValueError as error:
            raise revision_error("MODEL_SELECTION_INVALID") from error

    async def validate_for_job(
        self,
        model_id: str,
        revision: str,
        offline_mode: bool,
    ) -> ModelCatalogEntryDto:
        entry = await self.execute(model_id, revision, offline_mode)
        if not entry.cached:
            raise revision_error(
                "MODEL_NOT_CACHED",
                {"model_id": entry.model_id, "model_revision": entry.revision},
            )
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
        return entry


def _request(query: str, limit: int) -> tuple[str, int]:
    normalized = " ".join(query.strip().split())
    if len(normalized) > 200:
        raise revision_error("INVALID_INPUT", {"field": "model_query"})
    if not 1 <= limit <= 100:
        raise revision_error("INVALID_INPUT", {"field": "model_limit"})
    return normalized, limit
