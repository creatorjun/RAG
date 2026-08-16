from __future__ import annotations

import unittest
from dataclasses import replace
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
from enterprise_rag.domain.jobs import DocumentJobState


def _quality(valid: bool = True) -> FinalQualityReportDto:
    return FinalQualityReportDto(
        valid,
        () if valid else ("QUALITY_FAILED",),
        "a" * 64,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
    )


def _published() -> DocumentJobResultDto:
    return DocumentJobResultDto(
        "job-" + "a" * 32,
        DocumentJobState.COMPLETED,
        JobResultAvailability.PUBLISHED,
        True,
        _quality(),
        "/document.md",
        "/quality.json",
        "/comparison.json",
        "/comparison.md",
        "/synthesis.json",
        ComparisonCountsDto(1, 0, 0, 0),
        "b" * 64,
        "c" * 64,
    )


class JobResultDtoTest(unittest.TestCase):
    def test_comparison_counts_validate_and_total(self) -> None:
        self.assertEqual(ComparisonCountsDto(1, 2, 3, 4).total, 10)
        with self.assertRaises(ValueError):
            ComparisonCountsDto(-1, 0, 0, 0)

    def test_rejects_inconsistent_result_availability(self) -> None:
        job_id = "job-" + "b" * 32
        cases = (
            {
                "job_id": job_id,
                "job_state": DocumentJobState.CREATED,
                "availability": JobResultAvailability.NOT_READY,
                "notification_enabled": True,
                "quality": _quality(),
            },
            {
                "job_id": job_id,
                "job_state": DocumentJobState.CREATED,
                "availability": JobResultAvailability.NOT_READY,
                "notification_enabled": True,
                "quality_report_path": "/quality.json",
            },
            {
                "job_id": job_id,
                "job_state": DocumentJobState.VALIDATING_FINAL,
                "availability": JobResultAvailability.QUALITY_READY,
                "notification_enabled": True,
            },
            {
                "job_id": job_id,
                "job_state": DocumentJobState.VALIDATING_FINAL,
                "availability": JobResultAvailability.QUALITY_READY,
                "notification_enabled": True,
                "quality": _quality(),
                "quality_report_path": "/quality.json",
                "document_path": "/unexpected.md",
            },
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                DocumentJobResultDto(**values)

    def test_rejects_incomplete_or_invalid_published_result(self) -> None:
        valid = _published()
        cases = (
            {"document_path": None},
            {"comparison_report_sha256": "bad"},
            {"publication_fingerprint": "bad"},
            {"comparison_counts": ComparisonCountsDto(0, 0, 0, 0)},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(valid, **changes)

    def test_published_result_accepts_non_blocking_legacy_quality_report(self) -> None:
        result = replace(_published(), quality=_quality(False))

        self.assertFalse(result.quality.valid if result.quality is not None else True)

    def test_rejects_inconsistent_notification_receipts_and_claims(self) -> None:
        job_id = "job-" + "c" * 32
        now = datetime(2026, 8, 12, tzinfo=timezone.utc)
        valid_claim = CompletionNotificationDto(
            job_id,
            CompletionNotificationState.CLAIMED,
            "d" * 64,
            now,
        )
        cases = (
            {
                "job_id": job_id,
                "state": CompletionNotificationState.CLAIMED,
            },
            {
                "job_id": job_id,
                "state": CompletionNotificationState.CLAIMED,
                "publication_fingerprint": "bad",
                "claimed_at": now,
            },
            {
                "job_id": job_id,
                "state": CompletionNotificationState.CLAIMED,
                "publication_fingerprint": "d" * 64,
            },
            {
                "job_id": job_id,
                "state": CompletionNotificationState.DELIVERED,
                "publication_fingerprint": "d" * 64,
                "claimed_at": now,
            },
            {
                "job_id": job_id,
                "state": CompletionNotificationState.FAILED,
                "publication_fingerprint": "d" * 64,
                "claimed_at": now,
                "finished_at": now,
            },
            {
                "job_id": job_id,
                "state": CompletionNotificationState.DELIVERED,
                "publication_fingerprint": "d" * 64,
                "claimed_at": now,
                "finished_at": now,
                "error_code": "NOTIFICATION_FAILED",
            },
            {
                "job_id": job_id,
                "state": CompletionNotificationState.CLAIMED,
                "publication_fingerprint": "d" * 64,
                "claimed_at": now.replace(tzinfo=None),
            },
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                CompletionNotificationDto(**values)
        with self.assertRaises(ValueError):
            CompletionNotificationClaimDto(
                CompletionNotificationDto(
                    job_id,
                    CompletionNotificationState.READY,
                ),
                True,
            )
        self.assertTrue(CompletionNotificationClaimDto(valid_claim, True).acquired)


if __name__ == "__main__":
    unittest.main()
