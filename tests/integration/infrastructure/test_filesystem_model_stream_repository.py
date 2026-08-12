from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from enterprise_rag.application.dto.jobs import CreateDocumentJobDto
from enterprise_rag.application.dto.model_stream import (
    ModelStreamEventDto,
    ModelStreamEventKind,
)
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.jobs.filesystem_job_artifact_repository import (
    FilesystemJobArtifactRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_model_stream_repository import (
    FilesystemModelStreamRepository,
)


class FilesystemModelStreamRepositoryTest(unittest.TestCase):
    def test_appends_and_reads_bounded_job_scoped_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts = FilesystemJobArtifactRepository(root / "var")
            repository = FilesystemModelStreamRepository(root / "var")
            job = DocumentJob("job-" + "a" * 32)
            asyncio.run(
                artifacts.initialize(
                    job,
                    CreateDocumentJobDto(str(root), "작성", "out.md", "b" * 64),
                )
            )
            for sequence, (kind, text) in enumerate(
                (
                    (ModelStreamEventKind.STARTED, ""),
                    (ModelStreamEventKind.DELTA, "생성 중"),
                    (ModelStreamEventKind.COMPLETED, ""),
                ),
                start=1,
            ):
                repository.append(
                    ModelStreamEventDto(
                        job.job_id,
                        repository.next_sequence(job.job_id),
                        "generation-" + "1" * 32,
                        "CLAIM_DRAFT",
                        kind,
                        text,
                        datetime(2026, 8, 12, tzinfo=timezone.utc),
                    )
                )
                self.assertEqual(repository.next_sequence(job.job_id), sequence + 1)

            snapshot = asyncio.run(repository.snapshot(job.job_id, limit=2))

            self.assertEqual(snapshot.latest_sequence, 3)
            self.assertTrue(snapshot.truncated)
            self.assertEqual([event.sequence for event in snapshot.events], [2, 3])
            self.assertEqual(snapshot.events[0].text, "생성 중")

            repository.append(
                ModelStreamEventDto(
                    job.job_id,
                    4,
                    "generation-" + "2" * 32,
                    "TASK_OUTPUT",
                    ModelStreamEventKind.STARTED,
                    "",
                    datetime(2026, 8, 12, tzinfo=timezone.utc),
                )
            )
            repository.append(
                ModelStreamEventDto(
                    job.job_id,
                    5,
                    "generation-" + "2" * 32,
                    "TASK_OUTPUT",
                    ModelStreamEventKind.DELTA,
                    "가" * 4_096,
                    datetime(2026, 8, 12, tzinfo=timezone.utc),
                )
            )
            self.assertEqual(repository.next_sequence(job.job_id), 6)

    def test_rejects_conflicting_sequence_and_unknown_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifacts = FilesystemJobArtifactRepository(root / "var")
            repository = FilesystemModelStreamRepository(root / "var")
            job = DocumentJob("job-" + "c" * 32)
            asyncio.run(
                artifacts.initialize(
                    job,
                    CreateDocumentJobDto(str(root), "작성", "out.md", "d" * 64),
                )
            )
            event = ModelStreamEventDto(
                job.job_id,
                2,
                "generation-" + "2" * 32,
                "TASK_PLAN",
                ModelStreamEventKind.STARTED,
                "",
                datetime(2026, 8, 12, tzinfo=timezone.utc),
            )
            with self.assertRaises(ApplicationError) as captured:
                repository.append(event)
            self.assertEqual(captured.exception.code, "PROGRESS_EVENT_CONFLICT")
            with self.assertRaises(ApplicationError) as missing:
                asyncio.run(repository.snapshot("job-" + "f" * 32))
            self.assertEqual(missing.exception.code, "JOB_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
