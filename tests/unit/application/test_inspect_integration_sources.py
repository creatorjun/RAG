from __future__ import annotations

import asyncio
import unittest

from enterprise_rag.application.dto.long_document import (
    ChunkCoverageDto,
    ChunkingConfigDto,
    ChunkSetDto,
    LongTextChunkDto,
    SourceSpanDto,
    TextDocumentDto,
)
from enterprise_rag.application.progress import ProgressReporter
from enterprise_rag.application.use_cases.inspect_integration_sources import (
    InspectIntegrationSources,
)
from enterprise_rag.domain.errors import ApplicationError


class _FakeSource:
    def __init__(self, paths: tuple[str, ...]) -> None:
        self.paths = paths

    async def list_relative_paths(self) -> tuple[str, ...]:
        return self.paths

    async def read(self, relative_path: str) -> TextDocumentDto:
        return TextDocumentDto(
            f"revision:{relative_path}",
            relative_path,
            "a" * 64,
            f"content:{relative_path}",
        )


class _FakeChunker:
    def __init__(self, duplicate_ids: bool = False) -> None:
        self.duplicate_ids = duplicate_ids

    async def chunk(
        self,
        document: TextDocumentDto,
        config: ChunkingConfigDto,
    ) -> ChunkSetDto:
        chunk_id = "chunk:same" if self.duplicate_ids else f"chunk:{document.relative_path}"
        text = document.text
        chunk = LongTextChunkDto(
            chunk_id=chunk_id,
            revision_id=document.revision_id,
            ordinal=0,
            primary_text=text,
            context_prefix="",
            model_input=text,
            model_token_count=len(text),
            content_sha256="b" * 64,
            primary_span=SourceSpanDto(0, len(text)),
            context_span=None,
            previous_chunk_id=None,
            next_chunk_id=None,
        )
        coverage = ChunkCoverageDto(
            normalized_sha256="c" * 64,
            reconstructed_sha256="c" * 64,
            normalized_character_count=len(text),
            primary_covered_characters=len(text),
            missing_primary_characters=0,
            duplicate_primary_characters=0,
            context_reused_characters=0,
            complete=True,
        )
        return ChunkSetDto(
            revision_id=document.revision_id,
            relative_path=document.relative_path,
            source_sha256=document.source_sha256,
            normalized_sha256="c" * 64,
            normalized_text=text,
            chunks=(chunk,),
            coverage=coverage,
        )


_CONFIG = ChunkingConfigDto("tokenizer", "1", 128, 256, 1, 0.1)


class InspectIntegrationSourcesTest(unittest.TestCase):
    def test_assigns_every_chunk_to_exact_source_and_reports_document_counts(self) -> None:
        events = []
        use_case = InspectIntegrationSources(
            _FakeSource(("a.md", "b.md")),
            _FakeChunker(),
            _CONFIG,
        )
        result = asyncio.run(use_case.execute(ProgressReporter(events.append)))
        self.assertEqual(result.relative_paths, ("a.md", "b.md"))
        self.assertEqual(len(result.documents), 2)
        self.assertEqual(len(result.chunks), 2)
        self.assertEqual(len(result.chunk_source_by_id), 2)
        self.assertEqual(events[0].percentage, 0)
        self.assertEqual(events[-1].percentage, 20)
        self.assertEqual(events[-1].counter_name, "documents")
        self.assertEqual((events[-1].completed, events[-1].total), (2, 2))

    def test_rejects_duplicate_chunk_identity_across_documents(self) -> None:
        use_case = InspectIntegrationSources(
            _FakeSource(("a.md", "b.md")),
            _FakeChunker(duplicate_ids=True),
            _CONFIG,
        )
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(use_case.execute(ProgressReporter()))
        self.assertEqual(captured.exception.code, "DUPLICATE_PLAN_ITEM")

    def test_rejects_empty_collection(self) -> None:
        use_case = InspectIntegrationSources(_FakeSource(()), _FakeChunker(), _CONFIG)
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(use_case.execute(ProgressReporter()))
        self.assertEqual(captured.exception.code, "NO_TEXT_DOCUMENTS")


if __name__ == "__main__":
    unittest.main()
