from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum
from itertools import pairwise

_JOB_ID_PATTERN = re.compile(r"^job-[0-9a-f]{32}$")


class DocumentJobState(str, Enum):
    CREATED = "CREATED"
    INSPECTING = "INSPECTING"
    SNAPSHOTTING = "SNAPSHOTTING"
    EXTRACTING_EVIDENCE = "EXTRACTING_EVIDENCE"
    BUILDING_CLAIMS = "BUILDING_CLAIMS"
    PLANNING = "PLANNING"
    RUNNING_TASKS = "RUNNING_TASKS"
    VALIDATING_TASKS = "VALIDATING_TASKS"
    ASSEMBLING = "ASSEMBLING"
    VALIDATING_FINAL = "VALIDATING_FINAL"
    PUBLISHING = "PUBLISHING"
    COMPLETED = "COMPLETED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"

    @property
    def terminal(self) -> bool:
        return self in {
            DocumentJobState.COMPLETED,
            DocumentJobState.CANCELLED,
            DocumentJobState.FAILED,
        }


_NORMAL_FLOW = (
    DocumentJobState.CREATED,
    DocumentJobState.INSPECTING,
    DocumentJobState.SNAPSHOTTING,
    DocumentJobState.EXTRACTING_EVIDENCE,
    DocumentJobState.BUILDING_CLAIMS,
    DocumentJobState.PLANNING,
    DocumentJobState.RUNNING_TASKS,
    DocumentJobState.VALIDATING_TASKS,
    DocumentJobState.ASSEMBLING,
    DocumentJobState.VALIDATING_FINAL,
    DocumentJobState.PUBLISHING,
    DocumentJobState.COMPLETED,
)

_ALLOWED_TRANSITIONS = {
    current: {following} for current, following in pairwise(_NORMAL_FLOW)
}
for _active_state in _NORMAL_FLOW[:-1]:
    _ALLOWED_TRANSITIONS[_active_state].update(
        {
            DocumentJobState.CANCELLING,
            DocumentJobState.FAILED,
        }
    )
_ALLOWED_TRANSITIONS[DocumentJobState.VALIDATING_TASKS].add(
    DocumentJobState.NEEDS_ATTENTION
)
_ALLOWED_TRANSITIONS[DocumentJobState.VALIDATING_FINAL].add(
    DocumentJobState.NEEDS_ATTENTION
)
_ALLOWED_TRANSITIONS[DocumentJobState.NEEDS_ATTENTION] = {
    DocumentJobState.RUNNING_TASKS,
    DocumentJobState.ASSEMBLING,
    DocumentJobState.CANCELLING,
    DocumentJobState.FAILED,
}
_ALLOWED_TRANSITIONS[DocumentJobState.CANCELLING] = {
    DocumentJobState.CANCELLED,
    DocumentJobState.FAILED,
}
_ALLOWED_TRANSITIONS[DocumentJobState.FAILED] = {DocumentJobState.CREATED}


@dataclass(frozen=True, slots=True)
class DocumentJob:
    job_id: str
    state: DocumentJobState = DocumentJobState.CREATED
    last_event_sequence: int = 0
    last_percentage: int = 0

    def __post_init__(self) -> None:
        if not _JOB_ID_PATTERN.fullmatch(self.job_id):
            raise ValueError("invalid document job ID")
        if self.last_event_sequence < 0:
            raise ValueError("event sequence must be non-negative")
        if not 0 <= self.last_percentage <= 100:
            raise ValueError("job percentage must be between zero and one hundred")
        if self.state is DocumentJobState.COMPLETED and self.last_percentage != 100:
            raise ValueError("completed job must have one hundred percent progress")

    def transition(self, target: DocumentJobState) -> DocumentJob:
        if target not in _ALLOWED_TRANSITIONS.get(self.state, set()):
            raise ValueError(f"invalid document job transition: {self.state} -> {target}")
        percentage = 100 if target is DocumentJobState.COMPLETED else self.last_percentage
        return replace(self, state=target, last_percentage=percentage)

    def record_progress(self, sequence: int, percentage: int | None) -> DocumentJob:
        if self.state.terminal:
            raise ValueError("terminal job cannot record progress")
        if sequence != self.last_event_sequence + 1:
            raise ValueError("event sequence must increase by exactly one")
        next_percentage = self.last_percentage if percentage is None else percentage
        if next_percentage < self.last_percentage:
            raise ValueError("job percentage cannot decrease")
        if not 0 <= next_percentage <= 99:
            raise ValueError("running job percentage must be between zero and ninety-nine")
        return replace(
            self,
            last_event_sequence=sequence,
            last_percentage=next_percentage,
        )
