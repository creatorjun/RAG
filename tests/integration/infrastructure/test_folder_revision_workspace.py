# tests/integration/infrastructure/test_folder_revision_workspace.py
from __future__ import annotations

import asyncio
import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from enterprise_rag.application.dto.revision import (
    GeneratedDocumentWriteDto,
    SourceDocumentRecordDto,
)
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.revision import FileChangeStatus, RevisionRunState
from enterprise_rag.infrastructure.workspace.folder_revision_workspace import (
    FolderRevisionWorkspace,
)
from enterprise_rag.infrastructure.workspace.folder_tree_comparator import FolderTreeComparator


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 10, 3, 0, 0, tzinfo=timezone.utc)


class _SequenceIdGenerator:
    def __init__(self) -> None:
        self._value = 0

    def new_id(self) -> str:
        self._value += 1
        return f"{self._value:032x}"


def _workspace(before: Path, after: Path) -> FolderRevisionWorkspace:
    return FolderRevisionWorkspace(
        before,
        after,
        FolderTreeComparator(),
        _FixedClock(),
        _SequenceIdGenerator(),
        1024 * 1024,
    )


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


class FolderRevisionWorkspaceTest(unittest.TestCase):
    def test_generated_document_writer_records_manifest_and_blocks_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            before = root / "before"
            after = root / "after"
            before.mkdir()
            after.mkdir()
            (before / "document.md").write_text("source\n", encoding="utf-8")
            workspace = _workspace(before, after)
            run_id = "20260810t120000z-generated"
            asyncio.run(workspace.prepare_run(run_id))
            request = GeneratedDocumentWriteDto(
                "generated/integrated.md",
                "# Integrated\n",
                "test/model",
                "a" * 40,
                (SourceDocumentRecordDto("document.md", "b" * 64),),
                1,
                2,
            )
            written = asyncio.run(workspace.write_generated_document(run_id, request))
            self.assertEqual(written, "generated/integrated.md")
            self.assertTrue(
                (after / "runs" / run_id / "_reports" / "synthesis.json").is_file()
            )
            escaped = GeneratedDocumentWriteDto(
                "../escape.md",
                "blocked",
                "test/model",
                "a" * 40,
                (),
                0,
                0,
            )
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(workspace.write_generated_document(run_id, escaped))
            self.assertEqual(captured.exception.code, "PATH_ESCAPE")
            generated = after / "runs" / run_id / "documents" / "generated" / "integrated.md"
            generated.write_text("tampered\n", encoding="utf-8")
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(workspace.finalize_run(run_id))
            self.assertEqual(captured.exception.code, "COMPARISON_INCOMPLETE")

    def test_prepare_compare_finalize_and_preserve_before(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            before = root / "before"
            after = root / "after"
            before.mkdir()
            after.mkdir()
            (before / "modified.md").write_text("before\n", encoding="utf-8")
            (before / "removed.md").write_text("remove\n", encoding="utf-8")
            (before / "unchanged.md").write_text("same\n", encoding="utf-8")
            original_hash = _tree_hash(before)
            workspace = _workspace(before, after)
            run_id = "20260810t120000z-test"
            prepared = asyncio.run(workspace.prepare_run(run_id))
            documents = after / "runs" / run_id / "documents"
            (documents / "modified.md").write_text("after\n", encoding="utf-8")
            (documents / "added.md").write_text("added\n", encoding="utf-8")
            (documents / "removed.md").unlink()
            comparison = asyncio.run(workspace.compare_run(run_id))
            finalized = asyncio.run(workspace.finalize_run(run_id))
            self.assertEqual(prepared.state, RevisionRunState.PREPARED)
            self.assertEqual(
                comparison.counts,
                {"added": 1, "modified": 1, "removed": 1, "unchanged": 1},
            )
            statuses = {file.relative_path: file.status for file in comparison.files}
            self.assertEqual(statuses["added.md"], FileChangeStatus.ADDED)
            self.assertEqual(finalized.state, RevisionRunState.FINALIZED)
            self.assertEqual(_tree_hash(before), original_hash)
            self.assertTrue((after / "runs" / run_id / "_reports" / "comparison.md").is_file())
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(workspace.compare_run(run_id))
            self.assertEqual(captured.exception.code, "RUN_FINALIZED")

    def test_rejects_existing_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            before = root / "before"
            after = root / "after"
            before.mkdir()
            after.mkdir()
            (before / "document.md").write_text("text\n", encoding="utf-8")
            workspace = _workspace(before, after)
            run_id = "20260810t120000z-test"
            asyncio.run(workspace.prepare_run(run_id))
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(workspace.prepare_run(run_id))
            self.assertEqual(captured.exception.code, "RUN_ALREADY_EXISTS")

    def test_rejects_changed_before_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            before = root / "before"
            after = root / "after"
            before.mkdir()
            after.mkdir()
            source = before / "document.md"
            source.write_text("first\n", encoding="utf-8")
            workspace = _workspace(before, after)
            run_id = "20260810t120000z-test"
            asyncio.run(workspace.prepare_run(run_id))
            source.write_text("second\n", encoding="utf-8")
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(workspace.compare_run(run_id))
            self.assertEqual(captured.exception.code, "INPUT_HASH_CHANGED")

    def test_rejects_overlapping_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            root.mkdir(exist_ok=True)
            with self.assertRaises(ApplicationError) as captured:
                _workspace(root, root)
            self.assertEqual(captured.exception.code, "BEFORE_AFTER_OVERLAP")


if __name__ == "__main__":
    unittest.main()
