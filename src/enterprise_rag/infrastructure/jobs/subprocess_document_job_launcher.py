from __future__ import annotations

import asyncio
import fcntl
import os
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO

from enterprise_rag.application.dto.runner import RunnerLifecycle
from enterprise_rag.application.ports.clock import ClockPort, IdGeneratorPort
from enterprise_rag.application.ports.runner_lease_repository import (
    RunnerLeaseRepositoryPort,
)
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.workspace.path_security import (
    is_link_or_reparse,
    is_within,
)


class SubprocessDocumentJobLauncher:
    def __init__(
        self,
        project_root: Path,
        var_root: Path,
        environment: str,
        leases: RunnerLeaseRepositoryPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._project_root = project_root.resolve(strict=True)
        self._jobs_root = (var_root / "jobs").resolve(strict=True)
        self._environment = environment
        self._leases = leases
        self._clock = clock
        self._ids = ids

    async def launch(self, job_id: str) -> int:
        lock_stream = await asyncio.to_thread(self._acquire, job_id)
        runner_token = f"runner-{self._ids.new_id()}"
        launch_started = False
        try:
            await self._leases.begin_launch(job_id, runner_token, self._clock.now())
            launch_started = True
            return await asyncio.to_thread(
                self._spawn,
                job_id,
                runner_token,
                lock_stream,
            )
        except ApplicationError:
            raise
        except (OSError, subprocess.SubprocessError) as error:
            if launch_started:
                with suppress(ApplicationError):
                    await self._leases.finish(
                        job_id,
                        runner_token,
                        None,
                        RunnerLifecycle.FAILED,
                        self._clock.now(),
                        "JOB_LAUNCH_FAILED",
                    )
            raise revision_error("JOB_LAUNCH_FAILED", {"job_id": job_id}) from error
        finally:
            lock_stream.close()

    def _acquire(self, job_id: str) -> BinaryIO:
        try:
            DocumentJob(job_id)
        except ValueError as error:
            raise revision_error("INVALID_JOB_ID", {"job_id": job_id}) from error
        job_root = self._jobs_root / job_id
        if is_link_or_reparse(job_root):
            raise revision_error("LINK_NOT_ALLOWED", {"job_id": job_id})
        try:
            resolved_job_root = job_root.resolve(strict=True)
            if not resolved_job_root.is_dir() or not is_within(
                resolved_job_root, self._jobs_root
            ):
                raise revision_error("PATH_ESCAPE", {"job_id": job_id})
            lock_stream = (resolved_job_root / ".runner.lock").open("a+b")
            try:
                fcntl.flock(
                    lock_stream.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            except BlockingIOError as error:
                lock_stream.close()
                raise revision_error("JOB_ALREADY_RUNNING", {"job_id": job_id}) from error
            return lock_stream
        except ApplicationError:
            raise
        except OSError as error:
            raise revision_error("JOB_LAUNCH_FAILED", {"job_id": job_id}) from error

    def _spawn(
        self,
        job_id: str,
        runner_token: str,
        lock_stream: BinaryIO,
    ) -> int:
        log_path = Path(lock_stream.name).parent / "runner.log"
        with log_path.open("ab") as log_stream:
            process = subprocess.Popen(
                (
                    sys.executable,
                    "-m",
                    "enterprise_rag.presentation.job_worker",
                    "--project-root",
                    str(self._project_root),
                    "--environment",
                    self._environment,
                    "--job-id",
                    job_id,
                    "--lock-fd",
                    str(lock_stream.fileno()),
                    "--runner-token",
                    runner_token,
                ),
                stdin=subprocess.DEVNULL,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                pass_fds=(lock_stream.fileno(),),
                start_new_session=True,
                env=os.environ.copy(),
            )
        return int(process.pid)
