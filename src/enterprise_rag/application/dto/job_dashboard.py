from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import cast

from enterprise_rag.application.dto.jobs import DocumentJobDto
from enterprise_rag.application.dto.progress import ProgressEventDto
from enterprise_rag.application.dto.runner import RunnerStatusDto


class CheckpointStatus(str, Enum):
    MISSING = "MISSING"
    SAVED = "SAVED"
    IN_PROGRESS = "IN_PROGRESS"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class JobCheckpointDto:
    checkpoint_id: str
    label: str
    relative_path: str
    status: CheckpointStatus
    item_count: int | None
    resumable: bool
    detail: str

    def __post_init__(self) -> None:
        if not self.checkpoint_id or not self.label or not self.relative_path:
            raise ValueError("checkpoint identity is required")
        if self.item_count is not None and self.item_count < 0:
            raise ValueError("checkpoint item count must be non-negative")
        if not self.detail:
            raise ValueError("checkpoint detail is required")
        if self.status is CheckpointStatus.MISSING and self.resumable:
            raise ValueError("missing checkpoint cannot be resumable")
        if self.status is CheckpointStatus.INVALID and self.resumable:
            raise ValueError("invalid checkpoint cannot be resumable")


@dataclass(frozen=True, slots=True)
class JobDashboardDto:
    job: DocumentJobDto
    events: tuple[ProgressEventDto, ...]
    checkpoints: tuple[JobCheckpointDto, ...]
    runner: RunnerStatusDto | None = None

    def __post_init__(self) -> None:
        sequences = [event.sequence for event in self.events]
        if any(sequence is None for sequence in sequences):
            raise ValueError("dashboard events require persisted sequences")
        persisted_sequences = [cast(int, sequence) for sequence in sequences]
        if persisted_sequences != sorted(persisted_sequences):
            raise ValueError("dashboard events must be ordered")
        checkpoint_ids = [checkpoint.checkpoint_id for checkpoint in self.checkpoints]
        if len(checkpoint_ids) != len(set(checkpoint_ids)):
            raise ValueError("dashboard checkpoints must be unique")
