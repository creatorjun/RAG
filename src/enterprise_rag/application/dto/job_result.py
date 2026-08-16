from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from enterprise_rag.application.dto.tasks import FinalQualityReportDto
from enterprise_rag.domain.jobs import DocumentJob, DocumentJobState

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class JobResultAvailability(str, Enum):
    NOT_READY = "NOT_READY"
    QUALITY_READY = "QUALITY_READY"
    PUBLISHED = "PUBLISHED"


class CompletionNotificationState(str, Enum):
    NOT_READY = "NOT_READY"
    DISABLED = "DISABLED"
    READY = "READY"
    CLAIMED = "CLAIMED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ComparisonCountsDto:
    added: int
    modified: int
    removed: int
    unchanged: int

    def __post_init__(self) -> None:
        if min(self.added, self.modified, self.removed, self.unchanged) < 0:
            raise ValueError("comparison counts must be non-negative")

    @property
    def total(self) -> int:
        return self.added + self.modified + self.removed + self.unchanged


@dataclass(frozen=True, slots=True)
class DocumentJobResultDto:
    job_id: str
    job_state: DocumentJobState
    availability: JobResultAvailability
    notification_enabled: bool
    quality: FinalQualityReportDto | None = None
    document_path: str | None = None
    quality_report_path: str | None = None
    comparison_json_path: str | None = None
    comparison_markdown_path: str | None = None
    synthesis_report_path: str | None = None
    comparison_counts: ComparisonCountsDto | None = None
    comparison_report_sha256: str | None = None
    publication_fingerprint: str | None = None

    def __post_init__(self) -> None:
        DocumentJob(self.job_id)
        published_values = (
            self.document_path,
            self.comparison_json_path,
            self.comparison_markdown_path,
            self.synthesis_report_path,
            self.comparison_counts,
            self.comparison_report_sha256,
            self.publication_fingerprint,
        )
        if self.availability is JobResultAvailability.NOT_READY:
            if self.quality is not None or any(value is not None for value in published_values):
                raise ValueError("not-ready result cannot contain artifacts")
            if self.quality_report_path is not None:
                raise ValueError("not-ready result cannot contain a quality path")
            return
        if self.quality is None or self.quality_report_path is None:
            raise ValueError("available result requires final quality")
        if self.availability is JobResultAvailability.QUALITY_READY:
            if any(value is not None for value in published_values):
                raise ValueError("quality-only result cannot contain publication")
            return
        if any(value is None for value in published_values):
            raise ValueError("published result is incomplete")
        if not _SHA256.fullmatch(self.comparison_report_sha256 or ""):
            raise ValueError("invalid comparison report digest")
        if not _SHA256.fullmatch(self.publication_fingerprint or ""):
            raise ValueError("invalid publication fingerprint")
        if self.comparison_counts is None or self.comparison_counts.total < 1:
            raise ValueError("published result requires compared files")


@dataclass(frozen=True, slots=True)
class CompletionNotificationDto:
    job_id: str
    state: CompletionNotificationState
    publication_fingerprint: str | None = None
    claimed_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        DocumentJob(self.job_id)
        for value in (self.claimed_at, self.finished_at):
            if value is not None and value.utcoffset() is None:
                raise ValueError("notification timestamps must include a timezone")
        active = self.state in {
            CompletionNotificationState.CLAIMED,
            CompletionNotificationState.DELIVERED,
            CompletionNotificationState.FAILED,
        }
        if active != (self.publication_fingerprint is not None):
            raise ValueError("notification fingerprint is inconsistent")
        if active and not _SHA256.fullmatch(self.publication_fingerprint or ""):
            raise ValueError("invalid notification publication fingerprint")
        if active != (self.claimed_at is not None):
            raise ValueError("notification claim timestamp is inconsistent")
        terminal = self.state in {
            CompletionNotificationState.DELIVERED,
            CompletionNotificationState.FAILED,
        }
        if terminal != (self.finished_at is not None):
            raise ValueError("notification finish timestamp is inconsistent")
        if self.state is CompletionNotificationState.FAILED:
            if not self.error_code:
                raise ValueError("failed notification requires an error code")
        elif self.error_code is not None:
            raise ValueError("only failed notification can contain an error")


@dataclass(frozen=True, slots=True)
class CompletionNotificationClaimDto:
    receipt: CompletionNotificationDto
    acquired: bool

    def __post_init__(self) -> None:
        if self.acquired and self.receipt.state is not CompletionNotificationState.CLAIMED:
            raise ValueError("acquired notification claim must be pending")
