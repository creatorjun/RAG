from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from collections.abc import Callable
from pathlib import Path

from enterprise_rag.application.dto.jobs import DocumentJobDto
from enterprise_rag.application.dto.runner import RunnerLifecycle
from enterprise_rag.application.runtime import JobWorkerApplication
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJobState

LOGGER = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag-job-worker")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--environment",
        choices=("development", "test", "production"),
        required=True,
    )
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--lock-fd", type=int, required=True)
    parser.add_argument("--runner-token", required=True)
    return parser


async def _heartbeat(
    application: JobWorkerApplication,
    job_id: str,
    runner_token: str,
    pid: int,
) -> None:
    while True:
        await asyncio.sleep(application.heartbeat_seconds)
        await application.runner_leases.heartbeat(
            job_id,
            runner_token,
            pid,
            application.clock.now(),
        )
        LOGGER.debug(
            "job_worker_heartbeat",
            extra={"job_id": job_id, "worker_process_id": pid},
        )


async def _run_owned_job(
    application: JobWorkerApplication,
    job_id: str,
    runner_token: str,
) -> DocumentJobDto:
    pid = os.getpid()
    leases = application.runner_leases
    clock = application.clock
    loop = asyncio.get_running_loop()
    termination = application.termination
    confirmation_task: asyncio.Task[DocumentJobDto] | None = None

    def request_cancellation() -> None:
        nonlocal confirmation_task
        LOGGER.info(
            "job_worker_cancellation_requested",
            extra={"job_id": job_id, "worker_process_id": pid},
        )
        termination.request()
        if confirmation_task is None:
            confirmation_task = loop.create_task(
                application.confirm_document_job_cancellation.execute(job_id)
            )

    signal_registered = False
    try:
        loop.add_signal_handler(signal.SIGTERM, request_cancellation)
        signal_registered = True
    except (NotImplementedError, RuntimeError):
        signal_registered = False
    await leases.claim(job_id, runner_token, pid, clock.now())
    LOGGER.info(
        "job_worker_lease_claimed",
        extra={"job_id": job_id, "worker_process_id": pid},
    )
    run_task = asyncio.create_task(application.run_document_job.execute(job_id))
    heartbeat_task = asyncio.create_task(
        _heartbeat(application, job_id, runner_token, pid)
    )
    try:
        try:
            done, _ = await asyncio.wait(
                {run_task, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat_task in done:
                heartbeat_task.result()
                raise RuntimeError("heartbeat loop stopped unexpectedly")
            result = await run_task
            if result.state is DocumentJobState.COMPLETED:
                try:
                    await application.notify_document_job_completion.execute(job_id)
                except Exception:
                    # Notification delivery is an auxiliary side effect. The durable
                    # publication remains successful and the GUI can retry an unclaimed
                    # receipt without changing the Job result.
                    LOGGER.exception(
                        "completion_notification_failed",
                        extra={"job_id": job_id},
                    )
        finally:
            if not heartbeat_task.done():
                heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
    except ApplicationError as error:
        await leases.finish(
            job_id,
            runner_token,
            pid,
            RunnerLifecycle.FAILED,
            clock.now(),
            error.code,
        )
        raise
    except Exception:
        await leases.finish(
            job_id,
            runner_token,
            pid,
            RunnerLifecycle.FAILED,
            clock.now(),
            "WORKER_INTERNAL_FAILURE",
        )
        raise
    else:
        await leases.finish(
            job_id,
            runner_token,
            pid,
            RunnerLifecycle.EXITED,
            clock.now(),
        )
        return result
    finally:
        if not run_task.done():
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
        if confirmation_task is not None:
            await asyncio.gather(confirmation_task, return_exceptions=True)
        if signal_registered:
            loop.remove_signal_handler(signal.SIGTERM)
        termination.close()


def main(
    application_factory: Callable[[Path, str | None], JobWorkerApplication],
    argv: list[str] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    started_at = time.monotonic()
    try:
        os.fstat(args.lock_fd)
    except OSError:
        print("runner lock descriptor is not available", file=sys.stderr)
        return 2
    try:
        with application_factory(
            args.project_root,
            args.environment,
        ) as application:
            LOGGER.info(
                "job_worker_started",
                extra={
                    "job_id": args.job_id,
                    "worker_process_id": os.getpid(),
                    "environment": args.environment,
                },
            )
            result = asyncio.run(
                _run_owned_job(application, args.job_id, args.runner_token)
            )
    except ApplicationError as error:
        LOGGER.error(
            "job_worker_failed",
            extra={
                "job_id": args.job_id,
                "error_code": error.code,
                "error_category": error.category.value,
                "duration_ms": round((time.monotonic() - started_at) * 1000),
            },
            exc_info=True,
        )
        print(
            json.dumps(
                {
                    "code": error.code,
                    "category": error.category.value,
                    "message": error.safe_message,
                    "job_id": args.job_id,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    except Exception:
        LOGGER.exception(
            "job_worker_crashed",
            extra={
                "job_id": args.job_id,
                "duration_ms": round((time.monotonic() - started_at) * 1000),
            },
        )
        print("unhandled document job worker failure", file=sys.stderr)
        return 1
    LOGGER.info(
        "job_worker_completed",
        extra={
            "job_id": args.job_id,
            "job_state": result.state.value,
            "duration_ms": round((time.monotonic() - started_at) * 1000),
        },
    )
    print(
        json.dumps(
            {
                "job_id": result.job_id,
                "state": result.state.value,
                "last_percentage": result.last_percentage,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0
