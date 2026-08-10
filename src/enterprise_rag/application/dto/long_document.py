# src/enterprise_rag/application/dto/long_document.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextDocumentDto:
    revision_id: str
    relative_path: str
    source_sha256: str
    text: str


@dataclass(frozen=True, slots=True)
class ChunkingConfigDto:
    tokenizer_id: str
    chunker_version: str
    target_tokens: int
    max_tokens: int
    minimum_tokens: int
    overlap_ratio: float


@dataclass(frozen=True, slots=True)
class SourceSpanDto:
    start_char: int
    end_char: int


@dataclass(frozen=True, slots=True)
class LongTextChunkDto:
    chunk_id: str
    revision_id: str
    ordinal: int
    primary_text: str
    context_prefix: str
    model_input: str
    model_token_count: int
    content_sha256: str
    primary_span: SourceSpanDto
    context_span: SourceSpanDto | None
    previous_chunk_id: str | None
    next_chunk_id: str | None


@dataclass(frozen=True, slots=True)
class ChunkCoverageDto:
    normalized_sha256: str
    reconstructed_sha256: str
    normalized_character_count: int
    primary_covered_characters: int
    missing_primary_characters: int
    duplicate_primary_characters: int
    context_reused_characters: int
    complete: bool


@dataclass(frozen=True, slots=True)
class ChunkSetDto:
    revision_id: str
    relative_path: str
    source_sha256: str
    normalized_sha256: str
    normalized_text: str
    chunks: tuple[LongTextChunkDto, ...]
    coverage: ChunkCoverageDto


@dataclass(frozen=True, slots=True)
class ContextBatchDto:
    batch_id: str
    result_id: str
    purpose: str
    round_ordinal: int
    batch_ordinal: int
    item_ids: tuple[str, ...]
    input_tokens: int
    content_capacity_tokens: int
    total_planned_tokens: int
    maximum_context_tokens: int


@dataclass(frozen=True, slots=True)
class HierarchicalContextPlanDto:
    map_batches: tuple[ContextBatchDto, ...]
    reduce_rounds: tuple[tuple[ContextBatchDto, ...], ...]
    source_item_count: int
    root_result_id: str | None
    complete: bool


@dataclass(frozen=True, slots=True)
class LongDocumentPlanDto:
    chunks: ChunkSetDto
    context_plan: HierarchicalContextPlanDto
