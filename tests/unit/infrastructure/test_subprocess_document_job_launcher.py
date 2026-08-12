from __future__ import annotations

import asyncio
import fcntl
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from enterprise_rag.application.dto.jobs import CreateDocumentJobDto
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.jobs.filesystem_job_artifact_repository import (
    FilesystemJobArtifactRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_runner_lease_repository import (
    FilesystemRunnerLeaseRepository,
)
from enterprise_rag.infrastructure.jobs.subprocess_document_job_launcher import (
    SubprocessDocumentJobLauncher,
)


class SubprocessDocumentJobLauncherTest(unittest.TestCase):
    def _launcher(self, root: Path) -> SubprocessDocumentJobLauncher:
        clock = SimpleNamespace(now=lambda: datetime(2026, 8, 12, tzinfo=timezone.utc))
        ids = SimpleNamespace(new_id=lambda: "1" * 32)
        return SubprocessDocumentJobLauncher(
            root,
            root / "var",
            "development",
            FilesystemRunnerLeaseRepository(root / "var"),
            clock,
            ids,
        )

    def test_launches_detached_worker_with_inherited_lock_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            artifacts = FilesystemJobArtifactRepository(root / "var")
            job = DocumentJob("job-" + "a" * 32)
            asyncio.run(
                artifacts.initialize(
                    job,
                    CreateDocumentJobDto(str(root), "문서 작성", "out.md", "b" * 64),
                )
            )
            launcher = self._launcher(root)
            with patch(
                "enterprise_rag.infrastructure.jobs.subprocess_document_job_launcher."
                "subprocess.Popen",
                return_value=SimpleNamespace(pid=321),
            ) as popen:
                process_id = asyncio.run(launcher.launch(job.job_id))
            self.assertEqual(process_id, 321)
            arguments, options = popen.call_args
            self.assertIn(job.job_id, arguments[0])
            self.assertIn("runner-" + "1" * 32, arguments[0])
            self.assertTrue(options["start_new_session"])
            self.assertEqual(len(options["pass_fds"]), 1)

    def test_rejects_concurrent_runner_and_wraps_process_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            artifacts = FilesystemJobArtifactRepository(root / "var")
            job = DocumentJob("job-" + "c" * 32)
            asyncio.run(
                artifacts.initialize(
                    job,
                    CreateDocumentJobDto(str(root), "문서 작성", "out.md", "d" * 64),
                )
            )
            launcher = self._launcher(root)
            lock_path = root / "var/jobs" / job.job_id / ".runner.lock"
            with lock_path.open("a+b") as lock_stream:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(ApplicationError) as captured:
                    asyncio.run(launcher.launch(job.job_id))
                self.assertEqual(captured.exception.code, "JOB_ALREADY_RUNNING")
            with patch(
                "enterprise_rag.infrastructure.jobs.subprocess_document_job_launcher."
                "subprocess.Popen",
                side_effect=OSError("spawn failed"),
            ), self.assertRaises(ApplicationError) as captured:
                asyncio.run(launcher.launch(job.job_id))
            self.assertEqual(captured.exception.code, "JOB_LAUNCH_FAILED")
            lease = asyncio.run(
                FilesystemRunnerLeaseRepository(root / "var").load(job.job_id)
            )
            self.assertEqual(lease.error_code, "JOB_LAUNCH_FAILED")

    def test_rejects_invalid_or_missing_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "var/jobs").mkdir(parents=True)
            launcher = self._launcher(root)
            cases = (
                ("bad", "INVALID_JOB_ID"),
                ("job-" + "e" * 32, "JOB_LAUNCH_FAILED"),
            )
            for job_id, code in cases:
                with self.subTest(job_id=job_id), self.assertRaises(
                    ApplicationError
                ) as captured:
                    asyncio.run(launcher.launch(job_id))
                self.assertEqual(captured.exception.code, code)


if __name__ == "__main__":
    unittest.main()
