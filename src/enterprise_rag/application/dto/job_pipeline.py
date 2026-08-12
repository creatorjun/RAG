from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JobStageResultDto:
    message: str
    completed: int | None = None
    total: int | None = None
    counter_name: str | None = None
    needs_attention: bool = False

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("job stage result message is required")
        if (self.completed is None) != (self.total is None):
            raise ValueError("job stage counters must be provided together")
        if self.completed is not None and (
            self.completed < 0
            or self.total is None
            or self.total < 1
            or self.completed > self.total
        ):
            raise ValueError("invalid job stage counter")
        if self.counter_name is not None and not self.counter_name.strip():
            raise ValueError("job stage counter name must not be empty")
