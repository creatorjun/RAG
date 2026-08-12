from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from enterprise_rag.domain.jobs import DocumentJob

_RUNNER_TOKEN = re.compile(r"^runner-[0-9a-f]{32}$")


class RunnerLifecycle(str, Enum):
    LAUNCHING = "LAUNCHING"
    RUNNING = "RUNNING"
    EXITED = "EXITED"
    FAILED = "FAILED"


class RunnerHealth(str, Enum):
    STARTING = "STARTING"
    HEALTHY = "HEALTHY"
    STALE = "STALE"
    EXITED = "EXITED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class RunnerLeaseDto:
    job_id: str
    runner_token: str
    launch_sequence: int
    process_id: int | None
    lifecycle: RunnerLifecycle
    started_at: datetime
    heartbeat_at: datetime
    finished_at: datetime | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        DocumentJob(self.job_id)
        if _RUNNER_TOKEN.fullmatch(self.runner_token) is None:
            raise ValueError("runner token is invalid")
        if self.launch_sequence < 1:
            raise ValueError("launch sequence must be positive")
        if self.process_id is not None and self.process_id < 1:
            raise ValueError("process ID must be positive")
        for value in (self.started_at, self.heartbeat_at, self.finished_at):
            if value is not None and value.utcoffset() is None:
                raise ValueError("runner timestamps must include a timezone")
        if self.heartbeat_at < self.started_at:
            raise ValueError("heartbeat cannot precede runner start")
        terminal = self.lifecycle in {RunnerLifecycle.EXITED, RunnerLifecycle.FAILED}
        if terminal != (self.finished_at is not None):
            raise ValueError("runner terminal timestamp is inconsistent")
        if self.lifecycle is RunnerLifecycle.RUNNING and self.process_id is None:
            raise ValueError("running lease requires a process ID")
        if self.lifecycle is RunnerLifecycle.FAILED:
            if not self.error_code:
                raise ValueError("failed runner requires an error code")
        elif self.error_code is not None:
            raise ValueError("only a failed runner can have an error code")


@dataclass(frozen=True, slots=True)
class RunnerStatusDto:
    lease: RunnerLeaseDto
    health: RunnerHealth
    heartbeat_age_seconds: float

    def __post_init__(self) -> None:
        if self.heartbeat_age_seconds < 0:
            raise ValueError("heartbeat age must be non-negative")
