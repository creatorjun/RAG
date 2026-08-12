from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone

from enterprise_rag.application.dto.job_result import (
    ComparisonCountsDto,
    CompletionNotificationClaimDto,
    CompletionNotificationDto,
    CompletionNotificationState,
    DocumentJobResultDto,
    JobResultAvailability,
)
from enterprise_rag.application.dto.tasks import FinalQualityReportDto
from enterprise_rag.application.use_cases.notify_document_job_completion import (
    GetCompletionNotificationStatus,
    NotifyDocumentJobCompletion,
)
from enterprise_rag.domain.errors import revision_error
from enterprise_rag.domain.jobs import DocumentJob, DocumentJobState


class _Jobs:
    def __init__(self, job: DocumentJob) -> None:
        self.job = job

    async def get(self, job_id: str) -> DocumentJob | None:
        return self.job


class _Results:
    def __init__(self, result: DocumentJobResultDto) -> None:
        self.result = result

    async def inspect(self, job: DocumentJob) -> DocumentJobResultDto:
        return self.result


class _Receipts:
    def __init__(self, existing: CompletionNotificationDto | None = None) -> None:
        self.existing = existing
        self.finish_error: str | None = None

    async def get(self, job_id: str) -> CompletionNotificationDto | None:
        return self.existing

    async def claim(self, job_id, fingerprint, occurred_at):
        receipt = CompletionNotificationDto(
            job_id,
            CompletionNotificationState.CLAIMED,
            fingerprint,
            occurred_at,
        )
        self.existing = receipt
        return CompletionNotificationClaimDto(receipt, True)

    async def finish(self, job_id, fingerprint, occurred_at, error_code=None):
        self.finish_error = error_code
        state = (
            CompletionNotificationState.FAILED
            if error_code is not None
            else CompletionNotificationState.DELIVERED
        )
        self.existing = CompletionNotificationDto(
            job_id,
            state,
            fingerprint,
            self.existing.claimed_at,
            occurred_at,
            error_code,
        )
        return self.existing


class _Notifier:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def send(self, title: str, message: str) -> None:
        self.calls += 1
        if self.fail:
            raise revision_error("NOTIFICATION_FAILED")


class _Clock:
    @staticmethod
    def now() -> datetime:
        return datetime(2026, 8, 12, tzinfo=timezone.utc)


def _result(
    job: DocumentJob,
    availability: JobResultAvailability,
    enabled: bool,
) -> DocumentJobResultDto:
    if availability is not JobResultAvailability.PUBLISHED:
        return DocumentJobResultDto(job.job_id, job.state, availability, enabled)
    quality = FinalQualityReportDto(True, (), "a" * 64, 1, 1, 1, 1, 1, 1, 1)
    return DocumentJobResultDto(
        job.job_id,
        job.state,
        availability,
        enabled,
        quality,
        "/result.md",
        "/quality.json",
        "/comparison.json",
        "/comparison.md",
        "/synthesis.json",
        ComparisonCountsDto(1, 0, 0, 0),
        "b" * 64,
        "c" * 64,
    )


class NotifyDocumentJobCompletionTest(unittest.TestCase):
    def test_reports_not_ready_or_disabled_without_delivery(self) -> None:
        cases = (
            (
                DocumentJob("job-" + "a" * 32),
                JobResultAvailability.NOT_READY,
                True,
                CompletionNotificationState.NOT_READY,
            ),
            (
                DocumentJob(
                    "job-" + "b" * 32,
                    DocumentJobState.COMPLETED,
                    last_percentage=100,
                ),
                JobResultAvailability.PUBLISHED,
                False,
                CompletionNotificationState.DISABLED,
            ),
        )
        for job, availability, enabled, expected in cases:
            with self.subTest(expected=expected):
                notifier = _Notifier()
                result = _result(job, availability, enabled)
                status = asyncio.run(
                    NotifyDocumentJobCompletion(
                        _Jobs(job),
                        _Results(result),
                        _Receipts(),
                        notifier,
                        _Clock(),
                    ).execute(job.job_id)
                )
                self.assertEqual(status.state, expected)
                self.assertEqual(notifier.calls, 0)

    def test_persists_safe_failure_and_does_not_raise_into_completed_job(self) -> None:
        job = DocumentJob(
            "job-" + "c" * 32,
            DocumentJobState.COMPLETED,
            last_percentage=100,
        )
        receipts = _Receipts()
        notifier = _Notifier(fail=True)
        status = asyncio.run(
            NotifyDocumentJobCompletion(
                _Jobs(job),
                _Results(_result(job, JobResultAvailability.PUBLISHED, True)),
                receipts,
                notifier,
                _Clock(),
            ).execute(job.job_id)
        )
        self.assertEqual(status.state, CompletionNotificationState.FAILED)
        self.assertEqual(status.error_code, "NOTIFICATION_FAILED")
        self.assertEqual(receipts.finish_error, "NOTIFICATION_FAILED")

    def test_status_returns_existing_claim_without_new_side_effect(self) -> None:
        job = DocumentJob(
            "job-" + "d" * 32,
            DocumentJobState.COMPLETED,
            last_percentage=100,
        )
        existing = CompletionNotificationDto(
            job.job_id,
            CompletionNotificationState.CLAIMED,
            "c" * 64,
            _Clock.now(),
        )
        status = asyncio.run(
            GetCompletionNotificationStatus(
                _Jobs(job),
                _Results(_result(job, JobResultAvailability.PUBLISHED, True)),
                _Receipts(existing),
            ).execute(job.job_id)
        )
        self.assertEqual(status, existing)


if __name__ == "__main__":
    unittest.main()
