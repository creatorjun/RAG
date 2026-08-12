from __future__ import annotations

import asyncio
import errno
import os
import signal

from enterprise_rag.application.dto.runner import RunnerLifecycle
from enterprise_rag.application.ports.runner_lease_repository import (
    RunnerLeaseRepositoryPort,
)
from enterprise_rag.domain.errors import ApplicationError, revision_error


class PosixRunnerCancellation:
    def __init__(self, leases: RunnerLeaseRepositoryPort) -> None:
        self._leases = leases

    async def request(self, job_id: str) -> bool:
        lease = await self._leases.load(job_id)
        if (
            lease is None
            or lease.lifecycle is not RunnerLifecycle.RUNNING
            or lease.process_id is None
        ):
            return False
        return await asyncio.to_thread(self._signal, job_id, lease.process_id)

    @staticmethod
    def _signal(job_id: str, process_id: int) -> bool:
        try:
            if os.getpgid(process_id) != process_id:
                raise revision_error(
                    "RUNNER_PROCESS_MISMATCH",
                    {"job_id": job_id, "process_id": process_id},
                )
            os.killpg(process_id, signal.SIGTERM)
            return True
        except ApplicationError:
            raise
        except ProcessLookupError:
            return False
        except OSError as error:
            if error.errno == errno.ESRCH:
                return False
            raise revision_error(
                "RUNNER_CANCELLATION_FAILED",
                {"job_id": job_id, "process_id": process_id},
            ) from error
