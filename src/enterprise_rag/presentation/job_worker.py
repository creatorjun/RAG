from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from collections.abc import Callable
from pathlib import Path

from enterprise_rag.application.dto.jobs import DocumentJobDto
from enterprise_rag.application.dto.runner import RunnerLifecycle
from enterprise_rag.application.runtime import JobWorkerApplication
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJobState


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
                    pass
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
            result = asyncio.run(
                _run_owned_job(application, args.job_id, args.runner_token)
            )
    except ApplicationError as error:
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
        print("unhandled document job worker failure", file=sys.stderr)
        return 1
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
