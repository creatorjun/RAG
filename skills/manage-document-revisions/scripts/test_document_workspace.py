# skills/manage-document-revisions/scripts/test_document_workspace.py
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from compare_run import compare
from prepare_run import prepare, resolve_after


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
            self.assertIn("diffs/", (run_root / "_reports" / "comparison.md").read_text(encoding="utf-8"))

            with self.assertRaisesRegex(ValueError, "finalized run is immutable"):
                compare(before.resolve(), after.resolve(), "20260810t090000z-test", False)

            with self.assertRaises(FileExistsError):
                prepare(before.resolve(), after.resolve(), "20260810t090000z-test")

    def test_rejects_identical_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            before = Path(temporary) / "before"
            before.mkdir()
            with self.assertRaisesRegex(ValueError, "must differ"):
                prepare(before.resolve(), before.resolve(), "20260810t090000z-test")

    def test_missing_after_root_is_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "before" / "new-after"
            with self.assertRaises(FileNotFoundError):
                resolve_after(str(missing))
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

            with self.assertRaisesRegex(ValueError, "differs from input manifest"):
                compare(before.resolve(), after.resolve(), "20260810t090000z-test", True)


if __name__ == "__main__":
    unittest.main()
