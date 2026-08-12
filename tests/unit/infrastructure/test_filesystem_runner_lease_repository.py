from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from enterprise_rag.application.dto.jobs import CreateDocumentJobDto
from enterprise_rag.application.dto.runner import RunnerLifecycle
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.jobs.filesystem_job_artifact_repository import (
    FilesystemJobArtifactRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_runner_lease_repository import (
    FilesystemRunnerLeaseRepository,
)


class FilesystemRunnerLeaseRepositoryTest(unittest.TestCase):
    def _repository(self, root: Path, suffix: str = "a"):
        artifacts = FilesystemJobArtifactRepository(root / "var")
        job = DocumentJob("job-" + suffix * 32)
        asyncio.run(
            artifacts.initialize(
                job,
                CreateDocumentJobDto(str(root), "문서 작성", "out.md", "b" * 64),
            )
        )
        return job, FilesystemRunnerLeaseRepository(root / "var")

    def test_persists_owned_runner_lifecycle_and_launch_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, repository = self._repository(root)
            started = datetime(2026, 8, 12, tzinfo=timezone.utc)
            token = "runner-" + "1" * 32
            launch = asyncio.run(repository.begin_launch(job.job_id, token, started))
            self.assertEqual(launch.lifecycle, RunnerLifecycle.LAUNCHING)
            running = asyncio.run(
                repository.claim(job.job_id, token, 123, started + timedelta(seconds=1))
            )
            self.assertEqual(running.process_id, 123)
            self.assertEqual(
                asyncio.run(
                    repository.claim(
                        job.job_id,
                        token,
                        123,
                        started + timedelta(seconds=2),
                    )
                ),
                running,
            )
            with self.assertRaises(ApplicationError):
                asyncio.run(
                    repository.claim(
                        job.job_id,
                        token,
                        999,
                        started + timedelta(seconds=2),
                    )
                )
            heartbeat = asyncio.run(
                repository.heartbeat(
                    job.job_id,
                    token,
                    123,
                    started + timedelta(seconds=6),
                )
            )
            self.assertEqual(heartbeat.heartbeat_at, started + timedelta(seconds=6))
            exited = asyncio.run(
                repository.finish(
                    job.job_id,
                    token,
                    123,
                    RunnerLifecycle.EXITED,
                    started + timedelta(seconds=7),
                )
            )
            self.assertEqual(asyncio.run(repository.load(job.job_id)), exited)
            self.assertEqual(
                asyncio.run(
                    repository.finish(
                        job.job_id,
                        token,
                        123,
                        RunnerLifecycle.EXITED,
                        started + timedelta(seconds=7),
                    )
                ),
                exited,
            )
            next_launch = asyncio.run(
                repository.begin_launch(
                    job.job_id,
                    "runner-" + "2" * 32,
                    started + timedelta(seconds=8),
                )
            )
            self.assertEqual(next_launch.launch_sequence, 2)
            with self.assertRaises(ApplicationError):
                asyncio.run(
                    repository.finish(
                        job.job_id,
                        "runner-" + "2" * 32,
                        None,
                        RunnerLifecycle.RUNNING,
                        started + timedelta(seconds=9),
                    )
                )

    def test_rejects_wrong_owner_and_corrupt_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job, repository = self._repository(root, "c")
            started = datetime(2026, 8, 12, tzinfo=timezone.utc)
            token = "runner-" + "3" * 32
            asyncio.run(repository.begin_launch(job.job_id, token, started))
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(
                    repository.claim(
                        job.job_id,
                        "runner-" + "4" * 32,
                        123,
                        started,
                    )
                )
            self.assertEqual(captured.exception.code, "RUNNER_LEASE_CONFLICT")
            state_path = root / "var/jobs" / job.job_id / "runner-state.json"
            state_path.write_text("{}", encoding="utf-8")
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.load(job.job_id))
            self.assertEqual(captured.exception.code, "RUNNER_LEASE_INVALID")


if __name__ == "__main__":
    unittest.main()
