# src/enterprise_rag/infrastructure/chunking/structure_aware_text_chunker.py
from __future__ import annotations

import asyncio
import hashlib
import re
import unicodedata
from dataclasses import dataclass

from enterprise_rag.application.dto.long_document import (
    ChunkCoverageDto,
    ChunkingConfigDto,
    ChunkSetDto,
    LongTextChunkDto,
    SourceSpanDto,
    TextDocumentDto,
)
from enterprise_rag.application.ports.token_counter import TokenCounterPort
from enterprise_rag.domain.errors import revision_error


@dataclass(frozen=True, slots=True)
class _ChunkDraft:
    chunk_id: str
    ordinal: int
    primary_text: str
    context_prefix: str
    model_input: str
    model_token_count: int
    content_sha256: str
    primary_span: SourceSpanDto
    context_span: SourceSpanDto | None


class StructureAwareTextChunker:
    def __init__(self, token_counter: TokenCounterPort) -> None:
        self._token_counter = token_counter

    async def chunk(
        self,
        document: TextDocumentDto,
        config: ChunkingConfigDto,
    ) -> ChunkSetDto:
        return await asyncio.to_thread(self._chunk, document, config)

    def _chunk(self, document: TextDocumentDto, config: ChunkingConfigDto) -> ChunkSetDto:
        self._validate_config(config)
        normalized = self._normalize(document.text)
        normalized_sha256 = self._sha256(normalized)
        drafts: list[_ChunkDraft] = []
        cursor = 0
        while cursor < len(normalized):
            draft = self._create_draft(document, normalized, config, len(drafts), cursor)
            drafts.append(draft)
            cursor = draft.primary_span.end_char
        chunks = self._link_chunks(document.revision_id, drafts)
        coverage = self._coverage(normalized, normalized_sha256, chunks, config)
        if not coverage.complete:
            raise revision_error("CHUNK_COVERAGE_FAILED", {"revision_id": document.revision_id})
        return ChunkSetDto(
            revision_id=document.revision_id,
            relative_path=document.relative_path,
            source_sha256=document.source_sha256,
            normalized_sha256=normalized_sha256,
            normalized_text=normalized,
            chunks=chunks,
            coverage=coverage,
        )

    def _create_draft(
        self,
        document: TextDocumentDto,
        text: str,
        config: ChunkingConfigDto,
        ordinal: int,
        start: int,
    ) -> _ChunkDraft:
        desired_context_tokens = int(config.target_tokens * config.overlap_ratio)
        context_start = self._token_counter.suffix_start(text, start, desired_context_tokens)
        context_prefix = text[context_start:start]
        empty_primary_input = self._render_model_input(context_prefix, "")
        primary_capacity = config.max_tokens - self._token_counter.count(empty_primary_input)
        if primary_capacity <= 0:
            context_start = start
            context_prefix = ""
            empty_primary_input = self._render_model_input("", "")
            primary_capacity = config.max_tokens - self._token_counter.count(empty_primary_input)
        if primary_capacity <= 0:
            raise revision_error("CHUNK_BOUNDARY", {"ordinal": ordinal})
        maximum_end = self._token_counter.prefix_end(text, start, primary_capacity)
        if maximum_end <= start:
            raise revision_error("CHUNK_BOUNDARY", {"ordinal": ordinal})
        target_capacity = min(config.target_tokens, primary_capacity)
        target_end = self._token_counter.prefix_end(text, start, target_capacity)
        end = self._select_boundary(text, start, target_end, maximum_end, config.minimum_tokens)
        primary_text = text[start:end]
        model_input = self._render_model_input(context_prefix, primary_text)
        while end > start and self._token_counter.count(model_input) > config.max_tokens:
            end -= 1
            primary_text = text[start:end]
            model_input = self._render_model_input(context_prefix, primary_text)
        if end <= start:
            raise revision_error("CHUNK_BOUNDARY", {"ordinal": ordinal})
        model_token_count = self._token_counter.count(model_input)
        content_sha256 = self._sha256(primary_text)
        chunk_id = self._chunk_id(
            document.revision_id,
            config.chunker_version,
            ordinal,
            start,
            end,
            content_sha256,
        )
        return _ChunkDraft(
            chunk_id=chunk_id,
            ordinal=ordinal,
            primary_text=primary_text,
            context_prefix=context_prefix,
            model_input=model_input,
            model_token_count=model_token_count,
            content_sha256=content_sha256,
            primary_span=SourceSpanDto(start, end),
            context_span=(SourceSpanDto(context_start, start) if context_start < start else None),
        )

    def _select_boundary(
        self,
        text: str,
        start: int,
        target_end: int,
        maximum_end: int,
        minimum_tokens: int,
    ) -> int:
        if maximum_end == len(text):
            return maximum_end
        minimum_end = self._token_counter.prefix_end(text, start, minimum_tokens)
        lower_bound = min(minimum_end, target_end)
        backward = self._last_boundary(text, lower_bound, target_end)
        if backward is not None:
            return backward
        forward = self._first_boundary(text, target_end, maximum_end)
        if forward is not None:
            return forward
        return maximum_end

    @staticmethod
    def _last_boundary(text: str, start: int, end: int) -> int | None:
        segment = text[start:end]
        candidates: list[int] = []
        for pattern in (
            r"\n\n+",
            r"\n",
            r"[.!?\u3002\uFF01\uFF1F](?:\s+|$)",
            r"\s+",
        ):
            matches = list(re.finditer(pattern, segment))
            if matches:
                candidates.append(start + matches[-1].end())
                break
        return max(candidates) if candidates else None

    @staticmethod
    def _first_boundary(text: str, start: int, end: int) -> int | None:
        segment = text[start:end]
        for pattern in (
            r"\n\n+",
            r"\n",
            r"[.!?\u3002\uFF01\uFF1F](?:\s+|$)",
            r"\s+",
        ):
            match = re.search(pattern, segment)
            if match:
                return start + match.end()
        return None

    @staticmethod
    def _render_model_input(context_prefix: str, primary_text: str) -> str:
        if context_prefix:
            return (
                '<context-prefix process="false">\n'
                f"{context_prefix}\n"
                "</context-prefix>\n"
                '<primary-range process="true">\n'
                f"{primary_text}\n"
                "</primary-range>"
            )
        return f'<primary-range process="true">\n{primary_text}\n</primary-range>'

    @staticmethod
    def _normalize(text: str) -> str:
        newlines = text.replace("\r\n", "\n").replace("\r", "\n")
        return unicodedata.normalize("NFC", newlines)

    @staticmethod
    def _sha256(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _chunk_id(
        revision_id: str,
        chunker_version: str,
        ordinal: int,
        start: int,
        end: int,
        content_sha256: str,
    ) -> str:
        identity = f"{revision_id}\0{chunker_version}\0{ordinal}\0{start}\0{end}\0{content_sha256}"
        return f"sha256:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"

    @staticmethod
    def _link_chunks(
        revision_id: str,
        drafts: list[_ChunkDraft],
    ) -> tuple[LongTextChunkDto, ...]:
        return tuple(
            LongTextChunkDto(
                chunk_id=draft.chunk_id,
                revision_id=revision_id,
                ordinal=draft.ordinal,
                primary_text=draft.primary_text,
                context_prefix=draft.context_prefix,
                model_input=draft.model_input,
                model_token_count=draft.model_token_count,
                content_sha256=draft.content_sha256,
                primary_span=draft.primary_span,
                context_span=draft.context_span,
                previous_chunk_id=(drafts[index - 1].chunk_id if index > 0 else None),
                next_chunk_id=(drafts[index + 1].chunk_id if index + 1 < len(drafts) else None),
            )
            for index, draft in enumerate(drafts)
        )

    def _coverage(
        self,
        normalized: str,
        normalized_sha256: str,
        chunks: tuple[LongTextChunkDto, ...],
        config: ChunkingConfigDto,
    ) -> ChunkCoverageDto:
        cursor = 0
        duplicate = 0
        missing = 0
        primary_parts: list[str] = []
        links_valid = True
        contents_valid = True
        for index, chunk in enumerate(chunks):
            span = chunk.primary_span
            if span.start_char > cursor:
                missing += span.start_char - cursor
            elif span.start_char < cursor:
                duplicate += cursor - span.start_char
            expected_previous = chunks[index - 1].chunk_id if index > 0 else None
            expected_next = chunks[index + 1].chunk_id if index + 1 < len(chunks) else None
            links_valid = links_valid and chunk.previous_chunk_id == expected_previous
            links_valid = links_valid and chunk.next_chunk_id == expected_next
            primary_in_bounds = 0 <= span.start_char < span.end_char <= len(normalized)
            expected_primary = normalized[span.start_char : span.end_char]
            contents_valid = contents_valid and primary_in_bounds
            contents_valid = contents_valid and chunk.ordinal == index
            contents_valid = contents_valid and chunk.primary_text == expected_primary
            contents_valid = contents_valid and chunk.content_sha256 == self._sha256(
                expected_primary
            )
            if chunk.context_span is None:
                expected_context = ""
            else:
                context_span = chunk.context_span
                context_in_bounds = (
                    0 <= context_span.start_char <= context_span.end_char == span.start_char
                )
                expected_context = normalized[context_span.start_char : context_span.end_char]
                contents_valid = contents_valid and context_in_bounds
            expected_model_input = self._render_model_input(expected_context, expected_primary)
            actual_model_tokens = self._token_counter.count(chunk.model_input)
            contents_valid = contents_valid and chunk.context_prefix == expected_context
            contents_valid = contents_valid and chunk.model_input == expected_model_input
            contents_valid = contents_valid and chunk.model_token_count == actual_model_tokens
            contents_valid = contents_valid and actual_model_tokens <= config.max_tokens
            primary_parts.append(chunk.primary_text)
            cursor = max(cursor, span.end_char)
        if cursor < len(normalized):
            missing += len(normalized) - cursor
        reconstructed = "".join(primary_parts)
        reconstructed_sha256 = self._sha256(reconstructed)
        token_limits_valid = all(chunk.model_token_count > 0 for chunk in chunks)
        complete = (
            missing == 0
            and duplicate == 0
            and reconstructed == normalized
            and links_valid
            and contents_valid
            and token_limits_valid
        )
        return ChunkCoverageDto(
            normalized_sha256=normalized_sha256,
            reconstructed_sha256=reconstructed_sha256,
            normalized_character_count=len(normalized),
            primary_covered_characters=sum(
                chunk.primary_span.end_char - chunk.primary_span.start_char for chunk in chunks
            ),
            missing_primary_characters=missing,
            duplicate_primary_characters=duplicate,
            context_reused_characters=sum(len(chunk.context_prefix) for chunk in chunks),
            complete=complete,
        )

    def _validate_config(self, config: ChunkingConfigDto) -> None:
        if config.tokenizer_id != self._token_counter.identifier:
            raise revision_error("CONFIG_INVALID", {"field": "chunking.tokenizer_id"})
        if not 1 <= config.minimum_tokens <= config.target_tokens <= config.max_tokens:
            raise revision_error("CONFIG_INVALID", {"field": "chunking.token_limits"})
        if not 0 <= config.overlap_ratio <= 0.25:
            raise revision_error("CONFIG_INVALID", {"field": "chunking.overlap_ratio"})
