# src/enterprise_rag/application/use_cases/plan_long_document.py
from __future__ import annotations

from enterprise_rag.application.dto.long_document import (
    ChunkingConfigDto,
    LongDocumentPlanDto,
)
from enterprise_rag.application.ports.long_document import (
    HierarchicalContextPlannerPort,
    LongDocumentChunkerPort,
    TextDocumentSourcePort,
)
from enterprise_rag.domain.context_budget import TokenBudget
from enterprise_rag.domain.errors import revision_error


class PlanLongDocument:
    def __init__(
        self,
        source: TextDocumentSourcePort,
        chunker: LongDocumentChunkerPort,
        planner: HierarchicalContextPlannerPort,
        chunking_config: ChunkingConfigDto,
        map_budget: TokenBudget,
        reduce_budget: TokenBudget,
        separator_tokens: int,
    ) -> None:
        self._source = source
        self._chunker = chunker
        self._planner = planner
        self._chunking_config = chunking_config
        self._map_budget = map_budget
        self._reduce_budget = reduce_budget
        self._separator_tokens = separator_tokens

    async def execute(self, relative_path: str) -> LongDocumentPlanDto:
        document = await self._source.read(relative_path)
        chunks = await self._chunker.chunk(document, self._chunking_config)
        if not chunks.coverage.complete:
            raise revision_error("CHUNK_COVERAGE_FAILED", {"revision_id": document.revision_id})
        context_plan = self._planner.plan(
            chunks.chunks,
            self._map_budget,
            self._reduce_budget,
            self._separator_tokens,
        )
        if context_plan.source_item_count != len(chunks.chunks) or not context_plan.complete:
            raise revision_error("CHUNK_COVERAGE_FAILED", {"revision_id": document.revision_id})
        return LongDocumentPlanDto(chunks, context_plan)
