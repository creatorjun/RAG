from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from enterprise_rag.application.dto.progress import ProgressEventDto
from enterprise_rag.application.use_cases.manage_document_jobs import (
    GetDocumentJob,
    ListDocumentJobEvents,
    ListDocumentJobs,
    RequestDocumentJobCancellation,
)
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJob, DocumentJobState
from enterprise_rag.infrastructure.persistence.sqlite_document_job_repository import (
    SqliteDocumentJobRepository,
)


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 12, tzinfo=timezone.utc)


class ManageDocumentJobsTest(unittest.TestCase):
    def test_get_list_events_and_cancel_share_persisted_job_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = SqliteDocumentJobRepository(
                Path(temporary).resolve() / "metadata.sqlite3",
                _Clock(),
            )
            job = DocumentJob("job-" + "a" * 32)
            asyncio.run(repository.create(job))
            asyncio.run(
                repository.transition(
                    job.job_id,
                    DocumentJobState.CREATED,
                    DocumentJobState.INSPECTING,
                )
            )
            asyncio.run(
                repository.publish(
                    ProgressEventDto(
                        10,
                        "INSPECTING",
                        "검사 중",
                        1,
                        2,
                        "documents",
                        job.job_id,
                        1,
                    )
                )
            )
            restored = asyncio.run(GetDocumentJob(repository).execute(job.job_id))
            listed = asyncio.run(ListDocumentJobs(repository).execute(10))
            events = asyncio.run(
                ListDocumentJobEvents(repository).execute(job.job_id)
            )
            cancelling = asyncio.run(
                RequestDocumentJobCancellation(repository).execute(job.job_id)
            )
            repeated = asyncio.run(
                RequestDocumentJobCancellation(repository).execute(job.job_id)
            )
            self.assertEqual(restored.last_percentage, 10)
            self.assertEqual(listed[0].job_id, job.job_id)
            self.assertEqual(events[0].message, "검사 중")
            self.assertEqual(cancelling.state, DocumentJobState.CANCELLING)
            self.assertEqual(repeated, cancelling)

    def test_management_rejects_missing_job_and_invalid_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = SqliteDocumentJobRepository(
                Path(temporary).resolve() / "metadata.sqlite3",
                _Clock(),
            )
            unknown = "job-" + "b" * 32
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(GetDocumentJob(repository).execute(unknown))
            self.assertEqual(captured.exception.code, "JOB_NOT_FOUND")
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(ListDocumentJobs(repository).execute(0))
            self.assertEqual(captured.exception.code, "INVALID_INPUT")
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(RequestDocumentJobCancellation(repository).execute(unknown))
            self.assertEqual(captured.exception.code, "JOB_NOT_FOUND")

    def test_cancellation_is_noop_for_terminal_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = SqliteDocumentJobRepository(
                Path(temporary).resolve() / "metadata.sqlite3",
                _Clock(),
            )
            job = DocumentJob(
                "job-" + "c" * 32,
                DocumentJobState.COMPLETED,
                last_percentage=100,
            )
            asyncio.run(repository.create(job))
            result = asyncio.run(
                RequestDocumentJobCancellation(repository).execute(job.job_id)
            )
            self.assertEqual(result.state, DocumentJobState.COMPLETED)


if __name__ == "__main__":
    unittest.main()
