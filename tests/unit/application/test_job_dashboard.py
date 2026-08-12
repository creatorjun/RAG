from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone

from enterprise_rag.application.dto.job_dashboard import (
    CheckpointStatus,
    JobCheckpointDto,
    JobDashboardDto,
)
from enterprise_rag.application.dto.jobs import DocumentJobDto
from enterprise_rag.application.dto.progress import ProgressEventDto
from enterprise_rag.application.dto.runner import (
    RunnerHealth,
    RunnerLeaseDto,
    RunnerLifecycle,
    RunnerStatusDto,
)
from enterprise_rag.application.use_cases.get_job_dashboard import GetJobDashboard
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJob


class _Jobs:
    def __init__(self, job: DocumentJob | None) -> None:
        self.job = job

    async def get(self, job_id: str) -> DocumentJob | None:
        return self.job


class _Events:
    async def list_after(self, job_id: str, after_sequence: int = 0):
        return (ProgressEventDto(10, "INSPECTING", "검사 중", job_id=job_id, sequence=1),)


class _Checkpoints:
    async def inspect(self, job_id: str):
        return (
            JobCheckpointDto(
                "definition",
                "Job 정의",
                "definition.json",
                CheckpointStatus.SAVED,
                1,
                True,
                "검증됨",
            ),
        )


class _Runners:
    def __init__(self, lease: RunnerLeaseDto | None) -> None:
        self.lease = lease

    async def load(self, job_id: str):
        return self.lease


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class JobDashboardTest(unittest.TestCase):
    def test_combines_job_events_and_checkpoint_state(self) -> None:
        job = DocumentJob("job-" + "a" * 32)
        dashboard = asyncio.run(
            GetJobDashboard(_Jobs(job), _Events(), _Checkpoints()).execute(job.job_id)
        )
        self.assertEqual(dashboard.job.job_id, job.job_id)
        self.assertEqual(dashboard.events[0].sequence, 1)
        self.assertEqual(dashboard.checkpoints[0].status, CheckpointStatus.SAVED)

    def test_classifies_healthy_and_stale_runner_from_heartbeat_age(self) -> None:
        job = DocumentJob("job-" + "d" * 32)
        now = datetime(2026, 8, 12, tzinfo=timezone.utc)
        lease = RunnerLeaseDto(
            job.job_id,
            "runner-" + "1" * 32,
            1,
            123,
            RunnerLifecycle.RUNNING,
            now - timedelta(seconds=30),
            now - timedelta(seconds=10),
        )
        use_case = GetJobDashboard(
            _Jobs(job),
            _Events(),
            _Checkpoints(),
            _Runners(lease),
            _Clock(now),
            worker_heartbeat_seconds=5,
            worker_missed_heartbeats=3,
        )
        healthy = asyncio.run(use_case.execute(job.job_id))
        self.assertEqual(healthy.runner.health, RunnerHealth.HEALTHY)
        use_case._clock.value = now + timedelta(seconds=6)
        stale = asyncio.run(use_case.execute(job.job_id))
        self.assertEqual(stale.runner.health, RunnerHealth.STALE)

    def test_classifies_launching_and_terminal_runner_states(self) -> None:
        job = DocumentJob("job-" + "e" * 32)
        now = datetime(2026, 8, 12, tzinfo=timezone.utc)
        use_case = GetJobDashboard(
            _Jobs(job),
            _Events(),
            _Checkpoints(),
            _Runners(None),
            _Clock(now),
        )
        launching = RunnerLeaseDto(
            job.job_id,
            "runner-" + "2" * 32,
            1,
            None,
            RunnerLifecycle.LAUNCHING,
            now,
            now,
        )
        self.assertEqual(
            use_case._runner_status(launching).health,
            RunnerHealth.STARTING,
        )
        for lifecycle, health, error in (
            (RunnerLifecycle.EXITED, RunnerHealth.EXITED, None),
            (RunnerLifecycle.FAILED, RunnerHealth.FAILED, "FAILED"),
        ):
            lease = RunnerLeaseDto(
                job.job_id,
                "runner-" + "3" * 32,
                1,
                123,
                lifecycle,
                now,
                now,
                now,
                error,
            )
            with self.subTest(lifecycle=lifecycle):
                self.assertEqual(use_case._runner_status(lease).health, health)

    def test_rejects_invalid_runner_contracts_and_partial_health_dependency(self) -> None:
        job_id = "job-" + "f" * 32
        now = datetime(2026, 8, 12, tzinfo=timezone.utc)
        baseline = {
            "job_id": job_id,
            "runner_token": "runner-" + "4" * 32,
            "launch_sequence": 1,
            "process_id": None,
            "lifecycle": RunnerLifecycle.LAUNCHING,
            "started_at": now,
            "heartbeat_at": now,
        }
        invalid = (
            {"runner_token": "bad"},
            {"launch_sequence": 0},
            {"process_id": 0},
            {"started_at": now.replace(tzinfo=None)},
            {"heartbeat_at": now - timedelta(seconds=1)},
            {"finished_at": now},
            {"lifecycle": RunnerLifecycle.RUNNING},
            {
                "lifecycle": RunnerLifecycle.FAILED,
                "finished_at": now,
            },
            {"error_code": "UNEXPECTED"},
        )
        for changed in invalid:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                RunnerLeaseDto(**(baseline | changed))
        valid = RunnerLeaseDto(**baseline)
        with self.assertRaises(ValueError):
            RunnerStatusDto(valid, RunnerHealth.STARTING, -0.1)
        with self.assertRaises(ValueError):
            GetJobDashboard(
                _Jobs(None),
                _Events(),
                _Checkpoints(),
                _Runners(None),
            )

    def test_rejects_missing_job_and_inconsistent_dashboard_contracts(self) -> None:
        unknown = "job-" + "b" * 32
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(
                GetJobDashboard(_Jobs(None), _Events(), _Checkpoints()).execute(unknown)
            )
        self.assertEqual(captured.exception.code, "JOB_NOT_FOUND")
        with self.assertRaises(ValueError):
            JobCheckpointDto(
                "missing",
                "누락",
                "missing.json",
                CheckpointStatus.MISSING,
                None,
                True,
                "없음",
            )
        checkpoint = JobCheckpointDto(
            "one",
            "하나",
            "one.json",
            CheckpointStatus.SAVED,
            1,
            True,
            "저장됨",
        )
        job = DocumentJob("job-" + "c" * 32)
        with self.assertRaises(ValueError):
            JobDashboardDto(
                job=DocumentJobDto.from_domain(job),
                events=(
                    ProgressEventDto(20, "B", "b", job_id=job.job_id, sequence=2),
                    ProgressEventDto(10, "A", "a", job_id=job.job_id, sequence=1),
                ),
                checkpoints=(checkpoint, checkpoint),
            )


if __name__ == "__main__":
    unittest.main()
