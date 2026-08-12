from __future__ import annotations

import asyncio
import errno
import signal
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from enterprise_rag.application.dto.runner import RunnerLeaseDto, RunnerLifecycle
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.infrastructure.jobs.posix_runner_cancellation import (
    PosixRunnerCancellation,
)
from enterprise_rag.infrastructure.jobs.thread_cancellation import (
    ThreadCancellationToken,
)
from enterprise_rag.infrastructure.jobs.worker_termination import (
    WorkerTerminationGuard,
)


class _Leases:
    def __init__(self, lease: RunnerLeaseDto | None) -> None:
        self.lease = lease

    async def load(self, job_id: str) -> RunnerLeaseDto | None:
        return self.lease


def _lease(lifecycle: RunnerLifecycle = RunnerLifecycle.RUNNING) -> RunnerLeaseDto:
    now = datetime(2026, 8, 12, tzinfo=timezone.utc)
    return RunnerLeaseDto(
        job_id="job-" + "a" * 32,
        runner_token="runner-" + "b" * 32,
        launch_sequence=1,
        process_id=321 if lifecycle is RunnerLifecycle.RUNNING else None,
        lifecycle=lifecycle,
        started_at=now,
        heartbeat_at=now,
    )


class RunnerCancellationTest(unittest.TestCase):
    def test_signals_only_the_owned_independent_process_group(self) -> None:
        cancellation = PosixRunnerCancellation(_Leases(_lease()))
        with (
            patch("os.getpgid", return_value=321),
            patch("os.killpg") as killpg,
        ):
            self.assertTrue(asyncio.run(cancellation.request("job-" + "a" * 32)))
        killpg.assert_called_once_with(321, signal.SIGTERM)

    def test_ignores_missing_or_non_running_process(self) -> None:
        for lease in (None, _lease(RunnerLifecycle.LAUNCHING)):
            with self.subTest(lease=lease):
                self.assertFalse(
                    asyncio.run(
                        PosixRunnerCancellation(_Leases(lease)).request(
                            "job-" + "a" * 32
                        )
                    )
                )

    def test_rejects_process_group_mismatch_and_maps_signal_failure(self) -> None:
        cancellation = PosixRunnerCancellation(_Leases(_lease()))
        with (
            patch("os.getpgid", return_value=999),
            self.assertRaises(ApplicationError) as captured,
        ):
            asyncio.run(cancellation.request("job-" + "a" * 32))
        self.assertEqual(captured.exception.code, "RUNNER_PROCESS_MISMATCH")

        with (
            patch("os.getpgid", return_value=321),
            patch("os.killpg", side_effect=OSError(errno.EPERM, "denied")),
            self.assertRaises(ApplicationError) as captured,
        ):
            asyncio.run(cancellation.request("job-" + "a" * 32))
        self.assertEqual(captured.exception.code, "RUNNER_CANCELLATION_FAILED")

    def test_treats_already_exited_process_as_noop(self) -> None:
        cancellation = PosixRunnerCancellation(_Leases(_lease()))
        with patch("os.getpgid", side_effect=ProcessLookupError):
            self.assertFalse(asyncio.run(cancellation.request("job-" + "a" * 32)))

    def test_cooperative_token_and_grace_timer_are_idempotent(self) -> None:
        token = ThreadCancellationToken()
        timer = SimpleNamespace(start=Mock(), cancel=Mock(), daemon=False)
        with patch("threading.Timer", return_value=timer) as timer_factory:
            guard = WorkerTerminationGuard(token, 15)
            guard.request()
            guard.request()
            guard.close()
        self.assertTrue(token.is_cancelled)
        timer_factory.assert_called_once_with(15, guard._force_exit)
        timer.start.assert_called_once_with()
        timer.cancel.assert_called_once_with()

    def test_force_exit_targets_only_the_worker_group_or_process(self) -> None:
        with (
            patch("os.getpid", return_value=321),
            patch("os.getpgrp", return_value=321),
            patch("os.killpg") as killpg,
        ):
            WorkerTerminationGuard._force_exit()
        killpg.assert_called_once_with(321, signal.SIGKILL)

        with (
            patch("os.getpid", return_value=321),
            patch("os.getpgrp", return_value=111),
            patch("os.kill") as kill,
        ):
            WorkerTerminationGuard._force_exit()
        kill.assert_called_once_with(321, signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
