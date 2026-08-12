from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import unittest
from datetime import datetime, timezone

from enterprise_rag.application.dto.runner import RunnerLeaseDto, RunnerLifecycle
from enterprise_rag.infrastructure.jobs.posix_runner_cancellation import (
    PosixRunnerCancellation,
)


class _Leases:
    def __init__(self, process_id: int) -> None:
        now = datetime.now(timezone.utc)
        self._lease = RunnerLeaseDto(
            "job-" + "a" * 32,
            "runner-" + "b" * 32,
            1,
            process_id,
            RunnerLifecycle.RUNNING,
            now,
            now,
        )

    async def load(self, job_id: str) -> RunnerLeaseDto:
        return self._lease


@unittest.skipUnless(os.name == "posix", "POSIX process groups are required")
class RunnerProcessTerminationTest(unittest.TestCase):
    def test_controller_delivers_sigterm_to_an_isolated_worker(self) -> None:
        process = self._spawn(
            "import signal,sys,time;"
            "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));"
            "print('ready',flush=True);"
            "time.sleep(30)"
        )
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            self.assertTrue(
                asyncio.run(
                    PosixRunnerCancellation(_Leases(process.pid)).request(
                        "job-" + "a" * 32
                    )
                )
            )
            self.assertEqual(process.wait(timeout=3), 0)
        finally:
            self._cleanup(process)

    def test_worker_watchdog_force_stops_a_hung_generation_process(self) -> None:
        process = self._spawn(
            "import signal,time;"
            "from enterprise_rag.infrastructure.jobs.thread_cancellation import "
            "ThreadCancellationToken;"
            "from enterprise_rag.infrastructure.jobs.worker_termination import "
            "WorkerTerminationGuard;"
            "guard=WorkerTerminationGuard(ThreadCancellationToken(),1);"
            "signal.signal(signal.SIGTERM,lambda *_:guard.request());"
            "print('ready',flush=True);"
            "time.sleep(30)"
        )
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            os.killpg(process.pid, signal.SIGTERM)
            self.assertEqual(process.wait(timeout=4), -signal.SIGKILL)
        finally:
            self._cleanup(process)

    @staticmethod
    def _spawn(program: str) -> subprocess.Popen[str]:
        return subprocess.Popen(
            (sys.executable, "-c", program),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

    @staticmethod
    def _cleanup(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.getpgid(process.pid) == process.pid:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            return
        process.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
