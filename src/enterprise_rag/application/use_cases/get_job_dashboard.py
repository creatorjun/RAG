from __future__ import annotations

from enterprise_rag.application.dto.job_dashboard import JobDashboardDto
from enterprise_rag.application.dto.jobs import DocumentJobDto
from enterprise_rag.application.dto.model_stream import ModelStreamSnapshotDto
from enterprise_rag.application.dto.runner import (
    RunnerHealth,
    RunnerLeaseDto,
    RunnerLifecycle,
    RunnerStatusDto,
)
from enterprise_rag.application.ports.clock import ClockPort
from enterprise_rag.application.ports.job_checkpoint_inspector import (
    JobCheckpointInspectorPort,
)
from enterprise_rag.application.ports.job_repository import DocumentJobRepositoryPort
from enterprise_rag.application.ports.model_stream import ModelStreamRepositoryPort
from enterprise_rag.application.ports.progress_events import ProgressEventPublisherPort
from enterprise_rag.application.ports.runner_lease_repository import (
    RunnerLeaseRepositoryPort,
)
from enterprise_rag.domain.errors import ApplicationError, revision_error


class GetJobDashboard:
    def __init__(
        self,
        jobs: DocumentJobRepositoryPort,
        events: ProgressEventPublisherPort,
        checkpoints: JobCheckpointInspectorPort,
        runners: RunnerLeaseRepositoryPort | None = None,
        clock: ClockPort | None = None,
        worker_start_timeout_seconds: int = 30,
        worker_heartbeat_seconds: int = 5,
        worker_missed_heartbeats: int = 3,
        model_streams: ModelStreamRepositoryPort | None = None,
    ) -> None:
        self._jobs = jobs
        self._events = events
        self._checkpoints = checkpoints
        self._runners = runners
        self._clock = clock
        self._start_timeout = worker_start_timeout_seconds
        self._stale_timeout = worker_heartbeat_seconds * worker_missed_heartbeats
        self._model_streams = model_streams
        if (runners is None) != (clock is None):
            raise ValueError("runner repository and clock must be configured together")

    async def execute(self, job_id: str) -> JobDashboardDto:
        job = await self._jobs.get(job_id)
        if job is None:
            raise revision_error("JOB_NOT_FOUND", {"job_id": job_id})
        events = await self._events.list_after(job_id)
        checkpoints = await self._checkpoints.inspect(job_id)
        lease = None if self._runners is None else await self._runners.load(job_id)
        runner = None if lease is None else self._runner_status(lease)
        model_stream = ModelStreamSnapshotDto()
        if self._model_streams is not None:
            try:
                model_stream = await self._model_streams.snapshot(job_id)
            except ApplicationError:
                # A damaged optional observability log must not hide the job,
                # its durable checkpoints, or its cancellation controls.
                model_stream = ModelStreamSnapshotDto()
        return JobDashboardDto(
            job=DocumentJobDto.from_domain(job),
            events=events,
            checkpoints=checkpoints,
            runner=runner,
            model_stream=model_stream,
        )

    def _runner_status(self, lease: RunnerLeaseDto) -> RunnerStatusDto:
        if self._clock is None:
            raise RuntimeError("runner health clock is not configured")
        age = max(0.0, (self._clock.now() - lease.heartbeat_at).total_seconds())
        if lease.lifecycle is RunnerLifecycle.LAUNCHING:
            health = (
                RunnerHealth.STARTING
                if age <= self._start_timeout
                else RunnerHealth.STALE
            )
        elif lease.lifecycle is RunnerLifecycle.RUNNING:
            health = (
                RunnerHealth.HEALTHY
                if age <= self._stale_timeout
                else RunnerHealth.STALE
            )
        elif lease.lifecycle is RunnerLifecycle.EXITED:
            health = RunnerHealth.EXITED
        else:
            health = RunnerHealth.FAILED
        return RunnerStatusDto(lease, health, age)
