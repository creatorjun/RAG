# tests/unit/infrastructure/test_structure_aware_text_chunker.py
from __future__ import annotations

import asyncio
import hashlib
import unittest

from enterprise_rag.application.dto.long_document import ChunkingConfigDto, TextDocumentDto
from enterprise_rag.infrastructure.chunking.structure_aware_text_chunker import (
    StructureAwareTextChunker,
)
from enterprise_rag.infrastructure.tokenization.conservative_utf8 import (
    ConservativeUtf8TokenCounter,
)


def _document(text: str) -> TextDocumentDto:
    source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return TextDocumentDto("revision-1", "long.md", source_sha256, text)


def _config() -> ChunkingConfigDto:
    return ChunkingConfigDto(
        tokenizer_id="conservative-utf8-bytes-v1",
        chunker_version="1",
        target_tokens=256,
        max_tokens=512,
        minimum_tokens=64,
        overlap_ratio=0.2,
    )


class StructureAwareTextChunkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.counter = ConservativeUtf8TokenCounter()
        self.chunker = StructureAwareTextChunker(self.counter)

    def test_long_multilingual_document_has_exact_primary_coverage(self) -> None:
        paragraph = (
            "## 운영 절차\r\nOracle Linux 점검 문장입니다.🙂 명령 결과를 확인합니다.\r\n\r\n"
        )
        document = _document(paragraph * 600)
        first = asyncio.run(self.chunker.chunk(document, _config()))
        second = asyncio.run(self.chunker.chunk(document, _config()))
        self.assertGreater(len(first.chunks), 100)
        self.assertTrue(first.coverage.complete)
        self.assertEqual(first.coverage.missing_primary_characters, 0)
        self.assertEqual(first.coverage.duplicate_primary_characters, 0)
        self.assertGreater(first.coverage.context_reused_characters, 0)
        self.assertEqual(
            "".join(chunk.primary_text for chunk in first.chunks), first.normalized_text
        )
        self.assertEqual(
            [chunk.chunk_id for chunk in first.chunks],
            [chunk.chunk_id for chunk in second.chunks],
        )
        cursor = 0
        for chunk in first.chunks:
            self.assertEqual(chunk.primary_span.start_char, cursor)
            self.assertEqual(
                chunk.primary_text,
                first.normalized_text[chunk.primary_span.start_char : chunk.primary_span.end_char],
            )
            self.assertLessEqual(chunk.model_token_count, _config().max_tokens)
            cursor = chunk.primary_span.end_char
        self.assertEqual(cursor, len(first.normalized_text))

    def test_unbroken_text_is_split_without_loss(self) -> None:
        document = _document("한🙂A" * 5000)
        result = asyncio.run(self.chunker.chunk(document, _config()))
        self.assertTrue(result.coverage.complete)
        self.assertGreater(len(result.chunks), 1)
        self.assertEqual(
            "".join(chunk.primary_text for chunk in result.chunks), result.normalized_text
        )

    def test_empty_document_produces_complete_empty_plan(self) -> None:
        result = asyncio.run(self.chunker.chunk(_document(""), _config()))
        self.assertEqual(result.chunks, ())
        self.assertTrue(result.coverage.complete)
        self.assertEqual(result.coverage.primary_covered_characters, 0)


if __name__ == "__main__":
    unittest.main()
