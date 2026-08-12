from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProgressEventDto:
    percentage: int | None
    stage: str
    message: str
    completed: int | None = None
    total: int | None = None
    counter_name: str | None = None
    job_id: str | None = None
    sequence: int | None = None

    def __post_init__(self) -> None:
        if self.percentage is not None and not 0 <= self.percentage <= 100:
            raise ValueError("percentage must be between zero and one hundred")
        if not self.stage or not self.message:
            raise ValueError("progress stage and message are required")
        if (self.completed is None) != (self.total is None):
            raise ValueError("progress completed and total must be provided together")
        if self.completed is not None and (
            self.completed < 0
            or self.total is None
            or self.total < 1
            or self.completed > self.total
        ):
            raise ValueError("invalid progress counter")
        if self.sequence is not None and self.sequence < 1:
            raise ValueError("progress sequence must be positive")


IntegrationProgress = ProgressEventDto
