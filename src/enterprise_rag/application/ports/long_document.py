# src/enterprise_rag/application/ports/long_document.py
from typing import Protocol

from enterprise_rag.application.dto.long_document import (
    ChunkingConfigDto,
    ChunkSetDto,
    HierarchicalContextPlanDto,
    LongTextChunkDto,
    TextDocumentDto,
)
from enterprise_rag.domain.context_budget import TokenBudget


class TextDocumentSourcePort(Protocol):
    async def read(self, relative_path: str) -> TextDocumentDto:
        raise NotImplementedError


class LongDocumentChunkerPort(Protocol):
    async def chunk(
        self,
        document: TextDocumentDto,
        config: ChunkingConfigDto,
    ) -> ChunkSetDto:
        raise NotImplementedError


class HierarchicalContextPlannerPort(Protocol):
    def plan(
        self,
        chunks: tuple[LongTextChunkDto, ...],
        map_budget: TokenBudget,
        reduce_budget: TokenBudget,
        item_overhead_tokens: int,
        separator_tokens: int,
    ) -> HierarchicalContextPlanDto:
        raise NotImplementedError
