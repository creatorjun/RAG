# tests/acceptance/test_revision_cli.py
from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from enterprise_rag.application.dto.revision import (
    DocumentIntegrationDto,
    FolderComparisonDto,
    RevisionRunDto,
)
from enterprise_rag.bootstrap import build_application, build_job_application
from enterprise_rag.domain.revision import RevisionRunState
from enterprise_rag.presentation.cli import main


class RevisionCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.project_root = Path(self._temporary.name)
        source_root = Path(__file__).parents[2]
        shutil.copytree(source_root / "config", self.project_root / "config")
        self.before_root = self.project_root / "data" / "before"
        self.after_root = self.project_root / "data" / "after"
        self.before_root.mkdir(parents=True)
        self.after_root.mkdir(parents=True)
        self.application_factory = build_application
        self.job_application_factory = build_job_application

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _execute(self, *arguments: str) -> tuple[int, dict[str, object], str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        args = ["--project-root", str(self.project_root), *arguments]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(
                self.application_factory,
                self.job_application_factory,
                args,
            )
        output = stdout.getvalue().strip()
        error = stderr.getvalue().strip()
        payload = json.loads(output or error)
        return exit_code, payload, error

    def test_doctor_loads_default_and_environment_settings(self) -> None:
        exit_code, payload, error = self._execute("--environment", "development", "doctor")
        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["environment"], "development")
        self.assertFalse(payload["web_enabled"])

    def test_revision_commands_cover_four_states_and_finalization(self) -> None:
        (self.before_root / "modified.md").write_text("before\n", encoding="utf-8")
        (self.before_root / "removed.md").write_text("removed\n", encoding="utf-8")
        (self.before_root / "unchanged.md").write_text("same\n", encoding="utf-8")
        run_id = "20260810t120000z-cli"
        prepared_exit, prepared, _ = self._execute(
            "revision",
            "prepare",
            "--run-id",
            run_id,
        )
        self.assertEqual(prepared_exit, 0)
        self.assertEqual(prepared["state"], "prepared")
        documents = self.after_root / "runs" / run_id / "documents"
        (documents / "modified.md").write_text("after\n", encoding="utf-8")
        (documents / "added.md").write_text("added\n", encoding="utf-8")
        (documents / "removed.md").unlink()
        compared_exit, compared, _ = self._execute(
            "revision",
            "compare",
            "--run-id",
            run_id,
        )
        self.assertEqual(compared_exit, 0)
        self.assertEqual(
            compared["counts"],
            {"added": 1, "modified": 1, "removed": 1, "unchanged": 1},
        )
        finalized_exit, finalized, _ = self._execute(
            "revision",
            "finalize",
            "--run-id",
            run_id,
        )
        self.assertEqual(finalized_exit, 0)
        self.assertEqual(finalized["state"], "finalized")
        blocked_exit, blocked, error = self._execute(
            "revision",
            "compare",
            "--run-id",
            run_id,
        )
        self.assertEqual(blocked_exit, 2)
        self.assertNotEqual(error, "")
        self.assertEqual(blocked["code"], "RUN_FINALIZED")

    def test_rejects_invalid_and_duplicate_run_ids(self) -> None:
        (self.before_root / "document.md").write_text("content\n", encoding="utf-8")
        invalid_exit, invalid, _ = self._execute(
            "revision",
            "prepare",
            "--run-id",
            "../escape",
        )
        self.assertEqual(invalid_exit, 2)
        self.assertEqual(invalid["code"], "INVALID_RUN_ID")
        run_id = "20260810t120000z-duplicate"
        first_exit, _, _ = self._execute("revision", "prepare", "--run-id", run_id)
        second_exit, duplicate, _ = self._execute("revision", "prepare", "--run-id", run_id)
        self.assertEqual(first_exit, 0)
        self.assertEqual(second_exit, 2)
        self.assertEqual(duplicate["code"], "RUN_ALREADY_EXISTS")

    def test_long_document_plan_exceeds_context_without_loss_or_duplicate(self) -> None:
        paragraph = "## Oracle Linux 운영 기준\n긴 문서의 모든 문장을 정확히 처리합니다.🙂\n\n"
        (self.before_root / "long.md").write_text(paragraph * 3000, encoding="utf-8")
        exit_code, payload, error = self._execute(
            "document",
            "plan",
            "--relative-path",
            "long.md",
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        self.assertTrue(payload["plan_complete"])
        self.assertGreater(payload["chunk_count"], 1)
        self.assertGreater(payload["map_batch_count"], 1)
        self.assertGreater(len(payload["reduce_round_batch_counts"]), 0)
        self.assertEqual(payload["coverage"]["missing_primary_characters"], 0)
        self.assertEqual(payload["coverage"]["duplicate_primary_characters"], 0)
        self.assertTrue(payload["coverage"]["complete"])
        self.assertLessEqual(
            payload["max_planned_context_tokens"],
            payload["maximum_context_tokens"],
        )

    def test_document_integrate_dispatches_single_pipeline_command(self) -> None:
        run_id = "20260811t120000z-integrated"
        run = RevisionRunDto(
            run_id,
            RevisionRunState.PREPARED,
            "a" * 64,
            2,
            f"runs/{run_id}/documents",
            "2026-08-11T12:00:00Z",
            None,
        )
        comparison = FolderComparisonDto(
            run_id,
            "cmp-1",
            "2026-08-11T12:01:00Z",
            (),
            "b" * 64,
        )
        result = DocumentIntegrationDto(
            run,
            "integrated-technical-guide.md",
            "test/model",
            "c" * 40,
            2,
            3,
            2,
            comparison,
        )
        application = MagicMock()
        application.__enter__.return_value = application
        application.integrate_documents.execute = AsyncMock(return_value=result)
        with patch.object(
            self,
            "application_factory",
            return_value=application,
        ):
            exit_code, payload, error = self._execute("document", "integrate")
        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        self.assertEqual(payload["run_id"], run_id)
        self.assertEqual(
            payload["output_relative_path"],
            f"runs/{run_id}/documents/integrated-technical-guide.md",
        )
        application.integrate_documents.execute.assert_awaited_once_with(
            None,
            "integrated-technical-guide.md",
            progress=unittest.mock.ANY,
        )


if __name__ == "__main__":
    unittest.main()
