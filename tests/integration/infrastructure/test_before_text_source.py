# tests/integration/infrastructure/test_before_text_source.py
from __future__ import annotations

import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path

from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.infrastructure.sources.before_text_source import BeforeTextDocumentSource


class BeforeTextDocumentSourceTest(unittest.TestCase):
    def test_lists_supported_text_documents_in_stable_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            before = Path(temporary).resolve() / "before"
            (before / "nested").mkdir(parents=True)
            (before / "z.yaml").write_text("z: 1\n", encoding="utf-8")
            (before / "nested" / "a.md").write_text("a\n", encoding="utf-8")
            (before / "ignored.pdf").write_bytes(b"%PDF")
            source = BeforeTextDocumentSource(before, 1024)
            self.assertEqual(
                asyncio.run(source.list_relative_paths()),
                ("nested/a.md", "z.yaml"),
            )

    def test_reads_utf8_document_with_stable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            before = root / "before"
            before.mkdir()
            content = "Oracle Linux 운영 문서🙂\n"
            path = before / "document.md"
            path.write_text(content, encoding="utf-8")
            stored_content = path.read_bytes()
            source = BeforeTextDocumentSource(before, 1024)
            first = asyncio.run(source.read("document.md"))
            second = asyncio.run(source.read("document.md"))
            self.assertEqual(first, second)
            self.assertEqual(first.text, stored_content.decode("utf-8"))
            self.assertEqual(first.source_sha256, hashlib.sha256(stored_content).hexdigest())

    def test_rejects_path_escape_unsupported_encoding_and_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            before = root / "before"
            before.mkdir()
            (root / "outside.md").write_text("outside", encoding="utf-8")
            (before / "binary.pdf").write_bytes(b"%PDF")
            (before / "invalid.md").write_bytes(b"\xff\xfe")
            (before / "large.md").write_text("x" * 32, encoding="utf-8")
            source = BeforeTextDocumentSource(before, 16)
            cases = (
                ("../outside.md", "PATH_ESCAPE"),
                ("binary.pdf", "TEXT_FORMAT_UNSUPPORTED"),
                ("invalid.md", "TEXT_FORMAT_UNSUPPORTED"),
                ("large.md", "DOCUMENT_TOO_LARGE"),
                ("missing.md", "BEFORE_ROOT_NOT_READABLE"),
            )
            for relative_path, code in cases:
                with self.subTest(relative_path=relative_path):
                    with self.assertRaises(ApplicationError) as captured:
                        asyncio.run(source.read(relative_path))
                    self.assertEqual(captured.exception.code, code)


if __name__ == "__main__":
    unittest.main()
