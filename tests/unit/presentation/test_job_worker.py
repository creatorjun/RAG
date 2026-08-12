from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from enterprise_rag.application.dto.jobs import DocumentJobDto
from enterprise_rag.application.dto.runner import RunnerLifecycle
from enterprise_rag.domain.errors import revision_error
from enterprise_rag.domain.jobs import DocumentJobState
from enterprise_rag.presentation.job_worker import main


class _Run:
    def __init__(self, result=None, error=None, delay=0.0) -> None:
        self.result = result
        self.error = error
        self.delay = delay
        self.calls = []

    async def execute(self, job_id):
        self.calls.append(job_id)
        if self.delay:
            import asyncio

            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.result


class _Leases:
    def __init__(self) -> None:
        self.claims = []
        self.heartbeats = []
        self.finishes = []

    async def claim(self, *args):
        self.claims.append(args)

    async def heartbeat(self, *args):
        self.heartbeats.append(args)

    async def finish(self, *args):
        self.finishes.append(args)


class _Termination:
    def __init__(self) -> None:
        self.requests = 0
        self.closed = 0

    def request(self) -> None:
        self.requests += 1

    def close(self) -> None:
        self.closed += 1


class _Application:
    def __init__(self, run, heartbeat_seconds=5.0) -> None:
        self.run_document_job = run
        self.runner_leases = _Leases()
        self.clock = type(
            "Clock",
            (),
            {"now": staticmethod(lambda: datetime(2026, 8, 12, tzinfo=timezone.utc))},
        )()
        self.heartbeat_seconds = heartbeat_seconds
        self.termination = _Termination()
        self.confirm_document_job_cancellation = _Run()
        self.notify_document_job_completion = _Run()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class JobWorkerTest(unittest.TestCase):
    def test_returns_success_or_safe_application_failure(self) -> None:
        job_id = "job-" + "a" * 32
        result = DocumentJobDto(job_id, DocumentJobState.COMPLETED, 10, 100)
        with tempfile.TemporaryFile() as lock_stream:
            arguments = [
                "--project-root",
                str(Path.cwd()),
                "--environment",
                "test",
                "--job-id",
                job_id,
                "--lock-fd",
                str(lock_stream.fileno()),
                "--runner-token",
                "runner-" + "1" * 32,
            ]
            success = _Application(_Run(result=result))
            self.assertEqual(main(lambda *_: success, arguments), 0)
            self.assertEqual(
                success.runner_leases.finishes[-1][3], RunnerLifecycle.EXITED
            )
            self.assertEqual(success.notify_document_job_completion.calls, [job_id])
            failure = _Application(_Run(error=revision_error("IO_FAILURE")))
            self.assertEqual(main(lambda *_: failure, arguments), 2)
            self.assertEqual(
                failure.runner_leases.finishes[-1][3], RunnerLifecycle.FAILED
            )
            self.assertEqual(failure.runner_leases.finishes[-1][-1], "IO_FAILURE")
            internal = _Application(_Run(error=ValueError("unexpected")))
            self.assertEqual(main(lambda *_: internal, arguments), 1)
            self.assertEqual(
                internal.runner_leases.finishes[-1][-1],
                "WORKER_INTERNAL_FAILURE",
            )

    def test_emits_heartbeat_during_job_execution(self) -> None:
        job_id = "job-" + "c" * 32
        result = DocumentJobDto(job_id, DocumentJobState.COMPLETED, 10, 100)
        application = _Application(
            _Run(result=result, delay=0.025),
            heartbeat_seconds=0.005,
        )
        with tempfile.TemporaryFile() as lock_stream:
            code = main(
                lambda *_: application,
                [
                    "--project-root",
                    str(Path.cwd()),
                    "--environment",
                    "test",
                    "--job-id",
                    job_id,
                    "--lock-fd",
                    str(lock_stream.fileno()),
                    "--runner-token",
                    "runner-" + "2" * 32,
                ]
            )
        self.assertEqual(code, 0)
        self.assertGreaterEqual(len(application.runner_leases.heartbeats), 2)

    def test_rejects_closed_lock_descriptor(self) -> None:
        with tempfile.TemporaryFile() as lock_stream:
            descriptor = lock_stream.fileno()
        result = main(
            lambda *_: _Application(_Run()),
            [
                "--project-root",
                str(Path.cwd()),
                "--environment",
                "test",
                "--job-id",
                "job-" + "b" * 32,
                "--lock-fd",
                str(descriptor),
                "--runner-token",
                "runner-" + "3" * 32,
            ]
        )
        self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
