# skills/manage-document-revisions/scripts/test_document_workspace.py
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from compare_run import compare
from prepare_run import prepare, resolve_after

from enterprise_rag.domain.errors import ApplicationError


class DocumentWorkspaceTest(unittest.TestCase):
    def test_prepare_compare_and_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = root / "before"
            after = root / "after"
            before.mkdir()
            after.mkdir()
            (before / "modified.md").write_text("before\n", encoding="utf-8")
            (before / "removed.md").write_text("remove\n", encoding="utf-8")
            (before / "unchanged.md").write_text("same\n", encoding="utf-8")

            run_root = prepare(before.resolve(), after.resolve(), "20260810t090000z-test")
            documents = run_root / "documents"
            (documents / "modified.md").write_text("after\n", encoding="utf-8")
            (documents / "added.md").write_text("added\n", encoding="utf-8")
            (documents / "removed.md").unlink()

            report = compare(before.resolve(), after.resolve(), "20260810t090000z-test", True)

            self.assertEqual(
                report["counts"],
                {"added": 1, "modified": 1, "removed": 1, "unchanged": 1},
            )
            self.assertTrue((run_root / "_reports" / "comparison.json").is_file())
            self.assertTrue((run_root / "_reports" / "comparison.md").is_file())
            markdown_report = (run_root / "_reports" / "comparison.md").read_text(encoding="utf-8")
            self.assertIn("diffs/", markdown_report)

            with self.assertRaises(ApplicationError) as finalized_error:
                compare(before.resolve(), after.resolve(), "20260810t090000z-test", False)
            self.assertEqual(finalized_error.exception.code, "RUN_FINALIZED")

            with self.assertRaises(ApplicationError) as existing_error:
                prepare(before.resolve(), after.resolve(), "20260810t090000z-test")
            self.assertEqual(existing_error.exception.code, "RUN_ALREADY_EXISTS")

    def test_rejects_identical_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            before = Path(temporary) / "before"
            before.mkdir()
            with self.assertRaises(ApplicationError) as overlap_error:
                prepare(before.resolve(), before.resolve(), "20260810t090000z-test")
            self.assertEqual(overlap_error.exception.code, "BEFORE_AFTER_OVERLAP")

    def test_missing_after_root_is_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "before" / "new-after"
            with self.assertRaises(ApplicationError) as missing_error:
                resolve_after(str(missing))
            self.assertEqual(missing_error.exception.code, "IO_FAILURE")
            self.assertFalse(missing.exists())

    def test_compare_rejects_changed_before_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = root / "before"
            after = root / "after"
            before.mkdir()
            after.mkdir()
            source = before / "document.md"
            source.write_text("first\n", encoding="utf-8")
            prepare(before.resolve(), after.resolve(), "20260810t090000z-test")
            source.write_text("second\n", encoding="utf-8")

            with self.assertRaises(ApplicationError) as changed_error:
                compare(before.resolve(), after.resolve(), "20260810t090000z-test", True)
            self.assertEqual(changed_error.exception.code, "INPUT_HASH_CHANGED")


if __name__ == "__main__":
    unittest.main()
