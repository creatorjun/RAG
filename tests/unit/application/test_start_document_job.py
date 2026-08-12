from __future__ import annotations

import asyncio
import unittest

from enterprise_rag.application.use_cases.start_document_job import StartDocumentJob
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJob, DocumentJobState


class _Jobs:
    def __init__(self, job: DocumentJob | None) -> None:
        self.job = job

    async def get(self, job_id: str) -> DocumentJob | None:
        return self.job


class _Launcher:
    def __init__(self) -> None:
        self.calls = []

    async def launch(self, job_id: str) -> int:
        self.calls.append(job_id)
        return 321


class StartDocumentJobTest(unittest.TestCase):
    def test_launches_created_or_interrupted_active_job(self) -> None:
        launcher = _Launcher()
        job = DocumentJob("job-" + "a" * 32)
        result = asyncio.run(StartDocumentJob(_Jobs(job), launcher).execute(job.job_id))
        self.assertEqual(result.process_id, 321)
        self.assertEqual(launcher.calls, [job.job_id])

    def test_rejects_missing_terminal_and_attention_jobs(self) -> None:
        launcher = _Launcher()
        jobs = (
            None,
            DocumentJob(
                "job-" + "b" * 32,
                DocumentJobState.COMPLETED,
                last_percentage=100,
            ),
            DocumentJob("job-" + "c" * 32, DocumentJobState.NEEDS_ATTENTION),
        )
        for job in jobs:
            job_id = "job-" + "d" * 32 if job is None else job.job_id
            with self.subTest(job=job), self.assertRaises(ApplicationError):
                asyncio.run(StartDocumentJob(_Jobs(job), launcher).execute(job_id))
        self.assertEqual(launcher.calls, [])


if __name__ == "__main__":
    unittest.main()
