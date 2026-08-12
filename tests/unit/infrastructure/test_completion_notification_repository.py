from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from enterprise_rag.application.dto.job_result import CompletionNotificationState
from enterprise_rag.application.dto.jobs import CreateDocumentJobDto
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.jobs.filesystem_completion_notification_repository import (
    FilesystemCompletionNotificationRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_job_artifact_repository import (
    FilesystemJobArtifactRepository,
)


class CompletionNotificationRepositoryTest(unittest.TestCase):
    def test_claims_and_finishes_exactly_one_delivery_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job(root)
            repository = FilesystemCompletionNotificationRepository(root / "var")
            claimed_at = datetime(2026, 8, 12, tzinfo=timezone.utc)
            fingerprint = "a" * 64
            first = asyncio.run(
                repository.claim(job.job_id, fingerprint, claimed_at)
            )
            repeated = asyncio.run(
                repository.claim(job.job_id, fingerprint, claimed_at)
            )
            self.assertTrue(first.acquired)
            self.assertFalse(repeated.acquired)
            self.assertEqual(first.receipt.state, CompletionNotificationState.CLAIMED)

            delivered = asyncio.run(
                repository.finish(
                    job.job_id,
                    fingerprint,
                    claimed_at + timedelta(seconds=1),
                )
            )
            delivered_again = asyncio.run(
                repository.finish(
                    job.job_id,
                    fingerprint,
                    claimed_at + timedelta(seconds=1),
                )
            )
            self.assertEqual(delivered.state, CompletionNotificationState.DELIVERED)
            self.assertEqual(delivered_again, delivered)
            self.assertEqual(asyncio.run(repository.get(job.job_id)), delivered)

    def test_rejects_fingerprint_mismatch_and_corrupt_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            job = self._job(root)
            repository = FilesystemCompletionNotificationRepository(root / "var")
            now = datetime(2026, 8, 12, tzinfo=timezone.utc)
            asyncio.run(repository.claim(job.job_id, "a" * 64, now))
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.claim(job.job_id, "b" * 64, now))
            self.assertEqual(captured.exception.code, "NOTIFICATION_RECEIPT_INVALID")

            path = (
                root
                / "var/jobs"
                / job.job_id
                / "control/completion-notification.json"
            )
            path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.get(job.job_id))
            self.assertEqual(captured.exception.code, "NOTIFICATION_RECEIPT_INVALID")

    @staticmethod
    def _job(root: Path) -> DocumentJob:
        job = DocumentJob("job-" + "a" * 32)
        artifacts = FilesystemJobArtifactRepository(root / "var")
        asyncio.run(
            artifacts.initialize(
                job,
                CreateDocumentJobDto(str(root), "문서 작성", "out.md", "b" * 64),
            )
        )
        return job


if __name__ == "__main__":
    unittest.main()
