from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from enterprise_rag.application.dto.progress import ProgressEventDto
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJob, DocumentJobState
from enterprise_rag.infrastructure.persistence.sqlite_document_job_repository import (
    SqliteDocumentJobRepository,
)


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 12, 3, 0, 0, tzinfo=timezone.utc)


class SqliteDocumentJobRepositoryTest(unittest.TestCase):
    def test_persists_job_transition_and_reopens_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary).resolve() / "metadata.sqlite3"
            repository = SqliteDocumentJobRepository(database, _FixedClock())
            job = DocumentJob("job-" + "a" * 32)
            asyncio.run(repository.create(job))
            inspecting = asyncio.run(
                repository.transition(
                    job.job_id,
                    DocumentJobState.CREATED,
                    DocumentJobState.INSPECTING,
                )
            )
            reopened = SqliteDocumentJobRepository(database, _FixedClock())
            restored = asyncio.run(reopened.get(job.job_id))
            self.assertEqual(inspecting.state, DocumentJobState.INSPECTING)
            self.assertEqual(restored, inspecting)
            connection = sqlite3.connect(database)
            try:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM schema_migration").fetchone()[0],
                    1,
                )
            finally:
                connection.close()

    def test_compare_and_set_rejects_stale_and_invalid_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = SqliteDocumentJobRepository(
                Path(temporary).resolve() / "metadata.sqlite3",
                _FixedClock(),
            )
            job = DocumentJob("job-" + "b" * 32)
            asyncio.run(repository.create(job))
            asyncio.run(
                repository.transition(
                    job.job_id,
                    DocumentJobState.CREATED,
                    DocumentJobState.INSPECTING,
                )
            )
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(
                    repository.transition(
                        job.job_id,
                        DocumentJobState.CREATED,
                        DocumentJobState.INSPECTING,
                    )
                )
            self.assertEqual(captured.exception.code, "JOB_STATE_CONFLICT")
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(
                    repository.transition(
                        job.job_id,
                        DocumentJobState.INSPECTING,
                        DocumentJobState.RUNNING_TASKS,
                    )
                )
            self.assertEqual(captured.exception.code, "JOB_STATE_CONFLICT")

    def test_progress_event_and_job_counter_commit_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = SqliteDocumentJobRepository(
                Path(temporary).resolve() / "metadata.sqlite3",
                _FixedClock(),
            )
            job = DocumentJob("job-" + "c" * 32)
            asyncio.run(repository.create(job))
            asyncio.run(
                repository.transition(
                    job.job_id,
                    DocumentJobState.CREATED,
                    DocumentJobState.INSPECTING,
                )
            )
            first = ProgressEventDto(
                5,
                "INSPECTING",
                "원본 검사 중",
                1,
                3,
                "documents",
                job.job_id,
                1,
            )
            second = ProgressEventDto(
                10,
                "INSPECTING",
                "원본 검사 중",
                2,
                3,
                "documents",
                job.job_id,
                2,
            )
            asyncio.run(repository.publish(first))
            asyncio.run(repository.publish(second))
            restored = asyncio.run(repository.get(job.job_id))
            events = asyncio.run(repository.list_after(job.job_id, 1))
            self.assertIsNotNone(restored)
            self.assertEqual(restored.last_event_sequence, 2)
            self.assertEqual(restored.last_percentage, 10)
            self.assertEqual(events[0].sequence, 2)
            self.assertEqual(events[0].occurred_at, "2026-08-12T03:00:00Z")
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.publish(second))
            self.assertEqual(captured.exception.code, "PROGRESS_EVENT_CONFLICT")
            self.assertEqual(len(asyncio.run(repository.list_after(job.job_id))), 2)

    def test_rejects_duplicate_and_unknown_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = SqliteDocumentJobRepository(
                Path(temporary).resolve() / "metadata.sqlite3",
                _FixedClock(),
            )
            job = DocumentJob("job-" + "d" * 32)
            asyncio.run(repository.create(job))
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.create(job))
            self.assertEqual(captured.exception.code, "JOB_ALREADY_EXISTS")
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.list_after("job-" + "e" * 32))
            self.assertEqual(captured.exception.code, "JOB_NOT_FOUND")

    def test_lists_recent_jobs_with_a_bounded_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = SqliteDocumentJobRepository(
                Path(temporary).resolve() / "metadata.sqlite3",
                _FixedClock(),
            )
            first = DocumentJob("job-" + "1" * 32)
            second = DocumentJob("job-" + "2" * 32)
            asyncio.run(repository.create(first))
            asyncio.run(repository.create(second))
            self.assertEqual(asyncio.run(repository.list_recent(1)), (second,))
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.list_recent(0))
            self.assertEqual(captured.exception.code, "INVALID_INPUT")


if __name__ == "__main__":
    unittest.main()
