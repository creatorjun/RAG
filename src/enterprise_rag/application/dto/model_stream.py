from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

_GENERATION_ID = re.compile(r"^generation-[0-9a-f]{32}$")


class ModelStreamEventKind(str, Enum):
    STARTED = "STARTED"
    DELTA = "DELTA"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ModelStreamEventDto:
    job_id: str
    sequence: int
    generation_id: str
    stage: str
    kind: ModelStreamEventKind
    text: str
    occurred_at: datetime
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.job_id.startswith("job-") or self.sequence < 1:
            raise ValueError("invalid model stream identity")
        if _GENERATION_ID.fullmatch(self.generation_id) is None:
            raise ValueError("invalid model generation ID")
        if not self.stage or len(self.stage) > 64:
            raise ValueError("invalid model stream stage")
        if len(self.text) > 4_096:
            raise ValueError("model stream delta is too large")
        if self.occurred_at.utcoffset() is None:
            raise ValueError("model stream timestamp must include a timezone")
        if self.kind is ModelStreamEventKind.DELTA:
            if not self.text or self.error_code is not None:
                raise ValueError("invalid model stream delta")
        elif self.text:
            raise ValueError("only model stream deltas can contain text")
        if self.kind is ModelStreamEventKind.FAILED:
            if not self.error_code:
                raise ValueError("failed model stream requires an error code")
        elif self.error_code is not None:
            raise ValueError("only failed model stream can contain an error code")


@dataclass(frozen=True, slots=True)
class ModelStreamSnapshotDto:
    events: tuple[ModelStreamEventDto, ...] = ()
    latest_sequence: int = 0
    truncated: bool = False

    def __post_init__(self) -> None:
        sequences = [event.sequence for event in self.events]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("model stream events must be ordered and unique")
        if self.latest_sequence < (sequences[-1] if sequences else 0):
            raise ValueError("model stream latest sequence is invalid")
