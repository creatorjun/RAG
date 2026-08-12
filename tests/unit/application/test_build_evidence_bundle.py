from __future__ import annotations

import unittest

from enterprise_rag.application.dto.long_document import (
    ChunkSourceDto,
    IntegrationInputDto,
    LongTextChunkDto,
    SourceSpanDto,
    TextDocumentDto,
)
from enterprise_rag.application.progress import ProgressReporter
from enterprise_rag.application.use_cases.build_evidence_bundle import BuildEvidenceBundle
from enterprise_rag.domain.errors import ApplicationError


def _input(include_source: bool = True) -> IntegrationInputDto:
    document = TextDocumentDto("revision:1", "guide.md", "a" * 64, "source text")
    chunk = LongTextChunkDto(
        chunk_id="chunk:1",
        revision_id=document.revision_id,
        ordinal=0,
        primary_text="source text",
        context_prefix="",
        model_input="source text",
        model_token_count=11,
        content_sha256="b" * 64,
        primary_span=SourceSpanDto(0, 11),
        context_span=None,
        previous_chunk_id=None,
        next_chunk_id=None,
    )
    sources = (ChunkSourceDto(chunk.chunk_id, document.relative_path),) if include_source else ()
    return IntegrationInputDto((document,), (chunk,), sources)


class BuildEvidenceBundleTest(unittest.TestCase):
    def test_builds_deterministic_evidence_for_every_source_structure(self) -> None:
        events = []
        builder = BuildEvidenceBundle()
        first = builder.execute(_input(), ProgressReporter(events.append))
        second = builder.execute(_input())
        self.assertEqual(first, second)
        self.assertEqual(first.source_document_count, 1)
        self.assertEqual(first.source_structure_count, 1)
        self.assertEqual(first.items[0].relative_path, "guide.md")
        self.assertEqual((first.items[0].start_char, first.items[0].end_char), (0, 11))
        self.assertEqual(events[-1].counter_name, "evidence")
        self.assertEqual(events[-1].percentage, 21)

    def test_rejects_unassigned_source_structure(self) -> None:
        with self.assertRaises(ApplicationError) as captured:
            BuildEvidenceBundle().execute(_input(include_source=False))
        self.assertEqual(captured.exception.code, "EVIDENCE_COVERAGE_FAILED")


if __name__ == "__main__":
    unittest.main()
