from __future__ import annotations

import asyncio
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from enterprise_rag.application.dto.job_pipeline import JobStageResultDto
from enterprise_rag.application.dto.progress import ProgressEventDto
from enterprise_rag.application.use_cases.run_document_job import RunDocumentJob
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.domain.jobs import DocumentJob, DocumentJobState
from enterprise_rag.infrastructure.jobs.thread_cancellation import (
    ThreadCancellationToken,
)
from enterprise_rag.infrastructure.persistence.sqlite_document_job_repository import (
    SqliteDocumentJobRepository,
)

_ACTIVE_STATES = (
    DocumentJobState.INSPECTING,
    DocumentJobState.SNAPSHOTTING,
    DocumentJobState.EXTRACTING_EVIDENCE,
    DocumentJobState.BUILDING_CLAIMS,
    DocumentJobState.PLANNING,
    DocumentJobState.RUNNING_TASKS,
    DocumentJobState.VALIDATING_TASKS,
    DocumentJobState.ASSEMBLING,
    DocumentJobState.VALIDATING_FINAL,
    DocumentJobState.PUBLISHING,
)


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 12, 3, 0, 0, tzinfo=timezone.utc)


@dataclass
class _Stage:
    state: DocumentJobState
    needs_attention: bool = False
    failure_code: str | None = None
    unexpected_failure: bool = False
    calls: int = 0

    async def execute(self, job_id: str) -> JobStageResultDto:
        self.calls += 1
        if self.failure_code is not None:
            raise revision_error(self.failure_code, {"job_id": job_id})
        if self.unexpected_failure:
            raise RuntimeError("unexpected")
        return JobStageResultDto(
            message=f"{self.state.value} 완료",
            completed=1,
            total=1,
            counter_name="stages",
            needs_attention=self.needs_attention,
        )


@dataclass
class _CancellingStage:
    state: DocumentJobState
    repository: SqliteDocumentJobRepository

    async def execute(self, job_id: str) -> JobStageResultDto:
        await self.repository.transition(
            job_id,
            self.state,
            DocumentJobState.CANCELLING,
        )
        return JobStageResultDto("안전 취소 지점 도달", 1, 1, "stages")


class DocumentJobOrchestratorTest(unittest.TestCase):
    def test_rejects_missing_or_misordered_stage_registration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = SqliteDocumentJobRepository(
                Path(temporary).resolve() / "metadata.sqlite3",
                _FixedClock(),
            )
            with self.assertRaises(ValueError):
                RunDocumentJob(repository, repository, (_Stage(_ACTIVE_STATES[0]),))

    def test_runs_fixed_pipeline_with_persisted_monotonic_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = SqliteDocumentJobRepository(
                Path(temporary).resolve() / "metadata.sqlite3",
                _FixedClock(),
            )
            job = DocumentJob("job-" + "a" * 32)
            asyncio.run(repository.create(job))
            stages = tuple(_Stage(state) for state in _ACTIVE_STATES)
            result = asyncio.run(
                RunDocumentJob(repository, repository, stages).execute(job.job_id)
            )

            self.assertEqual(result.state, DocumentJobState.COMPLETED)
            self.assertEqual(result.last_percentage, 100)
            self.assertEqual(result.last_event_sequence, len(stages))
            events = asyncio.run(repository.list_after(job.job_id))
            self.assertEqual(len(events), len(stages))
            self.assertEqual(events[-1].percentage, 99)
            self.assertEqual(
                [event.sequence for event in events],
                list(range(1, len(stages) + 1)),
            )
            self.assertEqual([stage.calls for stage in stages], [1] * len(stages))

    def test_quality_advisory_does_not_stop_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = SqliteDocumentJobRepository(
                Path(temporary).resolve() / "metadata.sqlite3",
                _FixedClock(),
            )
            job = DocumentJob("job-" + "b" * 32)
            asyncio.run(repository.create(job))
            stages = tuple(
                _Stage(
                    state,
                    needs_attention=state is DocumentJobState.VALIDATING_TASKS,
                )
                for state in _ACTIVE_STATES
            )
            result = asyncio.run(
                RunDocumentJob(repository, repository, stages).execute(job.job_id)
            )

            self.assertEqual(result.state, DocumentJobState.COMPLETED)
            self.assertEqual(sum(stage.calls for stage in stages), len(_ACTIVE_STATES))
            self.assertEqual(
                len(asyncio.run(repository.list_after(job.job_id))),
                len(_ACTIVE_STATES),
            )

    def test_marks_job_failed_when_stage_raises_application_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = SqliteDocumentJobRepository(
                Path(temporary).resolve() / "metadata.sqlite3",
                _FixedClock(),
            )
            job = DocumentJob("job-" + "c" * 32)
            asyncio.run(repository.create(job))
            stages = tuple(
                _Stage(
                    state,
                    failure_code=(
                        "MODEL_GENERATION_FAILED"
                        if state is DocumentJobState.RUNNING_TASKS
                        else None
                    ),
                )
                for state in _ACTIVE_STATES
            )
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(
                    RunDocumentJob(repository, repository, stages).execute(job.job_id)
                )
            self.assertEqual(captured.exception.code, "MODEL_GENERATION_FAILED")
            restored = asyncio.run(repository.get(job.job_id))
            self.assertIsNotNone(restored)
            self.assertEqual(restored.state, DocumentJobState.FAILED)

    def test_handles_unknown_terminal_cancelling_and_attention_states(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = SqliteDocumentJobRepository(
                Path(temporary).resolve() / "metadata.sqlite3",
                _FixedClock(),
            )
            stages = tuple(_Stage(state) for state in _ACTIVE_STATES)
            runner = RunDocumentJob(repository, repository, stages)
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(runner.execute("job-" + "d" * 32))
            self.assertEqual(captured.exception.code, "JOB_NOT_FOUND")

            completed = DocumentJob(
                "job-" + "e" * 32,
                DocumentJobState.COMPLETED,
                last_percentage=100,
            )
            cancelling = DocumentJob(
                "job-" + "f" * 32,
                DocumentJobState.CANCELLING,
            )
            attention = DocumentJob(
                "job-" + "1" * 32,
                DocumentJobState.NEEDS_ATTENTION,
            )
            for job in (completed, cancelling, attention):
                asyncio.run(repository.create(job))
            self.assertEqual(
                asyncio.run(runner.execute(completed.job_id)).state,
                DocumentJobState.COMPLETED,
            )
            self.assertEqual(
                asyncio.run(runner.execute(cancelling.job_id)).state,
                DocumentJobState.CANCELLED,
            )
            self.assertEqual(
                asyncio.run(runner.execute(attention.job_id)).state,
                DocumentJobState.COMPLETED,
            )

    def test_ignores_quality_advisory_and_wraps_unknown_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = SqliteDocumentJobRepository(
                Path(temporary).resolve() / "metadata.sqlite3",
                _FixedClock(),
            )
            invalid_attention = DocumentJob("job-" + "2" * 32)
            unexpected = DocumentJob("job-" + "3" * 32)
            asyncio.run(repository.create(invalid_attention))
            asyncio.run(repository.create(unexpected))
            attention_stages = tuple(
                _Stage(state, needs_attention=state is DocumentJobState.INSPECTING)
                for state in _ACTIVE_STATES
            )
            result = asyncio.run(
                RunDocumentJob(
                    repository,
                    repository,
                    attention_stages,
                ).execute(invalid_attention.job_id)
            )
            self.assertEqual(result.state, DocumentJobState.COMPLETED)

            failure_stages = tuple(
                _Stage(
                    state,
                    unexpected_failure=state is DocumentJobState.INSPECTING,
                )
                for state in _ACTIVE_STATES
            )
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(
                    RunDocumentJob(
                        repository,
                        repository,
                        failure_stages,
                    ).execute(unexpected.job_id)
                )
            self.assertEqual(captured.exception.code, "IO_FAILURE")

    def test_resume_skips_stage_whose_event_was_already_committed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = SqliteDocumentJobRepository(
                Path(temporary).resolve() / "metadata.sqlite3",
                _FixedClock(),
            )
            job = DocumentJob("job-" + "4" * 32)
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
                        DocumentJobState.INSPECTING.value,
                        "검사 완료",
                        1,
                        1,
                        "stages",
                        job.job_id,
                        1,
                    )
                )
            )
            stages = tuple(_Stage(state) for state in _ACTIVE_STATES)
            result = asyncio.run(
                RunDocumentJob(repository, repository, stages).execute(job.job_id)
            )
            self.assertEqual(result.state, DocumentJobState.COMPLETED)
            self.assertEqual(stages[0].calls, 0)
            self.assertEqual([stage.calls for stage in stages[1:]], [1] * 9)

    def test_confirms_cancellation_at_stage_boundary_without_publishing_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = SqliteDocumentJobRepository(
                Path(temporary).resolve() / "metadata.sqlite3",
                _FixedClock(),
            )
            job = DocumentJob("job-" + "5" * 32)
            asyncio.run(repository.create(job))
            stages = (
                _CancellingStage(DocumentJobState.INSPECTING, repository),
                *tuple(_Stage(state) for state in _ACTIVE_STATES[1:]),
            )
            result = asyncio.run(
                RunDocumentJob(repository, repository, stages).execute(job.job_id)
            )
            self.assertEqual(result.state, DocumentJobState.CANCELLED)
            self.assertEqual(asyncio.run(repository.list_after(job.job_id)), ())
            self.assertEqual([stage.calls for stage in stages[1:]], [0] * 9)

    def test_cancelled_token_stops_before_starting_the_first_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = SqliteDocumentJobRepository(
                Path(temporary).resolve() / "metadata.sqlite3",
                _FixedClock(),
            )
            job = DocumentJob("job-" + "6" * 32)
            asyncio.run(repository.create(job))
            stages = tuple(_Stage(state) for state in _ACTIVE_STATES)
            cancellation = ThreadCancellationToken()
            cancellation.cancel()
            result = asyncio.run(
                RunDocumentJob(
                    repository,
                    repository,
                    stages,
                    cancellation,
                ).execute(job.job_id)
            )
            self.assertEqual(result.state, DocumentJobState.CANCELLED)
            self.assertEqual([stage.calls for stage in stages], [0] * 10)


if __name__ == "__main__":
    unittest.main()
