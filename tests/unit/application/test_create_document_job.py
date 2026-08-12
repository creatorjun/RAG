from __future__ import annotations

import asyncio
import unittest

from enterprise_rag.application.dto.jobs import CreateDocumentJobDto
from enterprise_rag.application.use_cases.create_document_job import CreateDocumentJob
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.domain.jobs import DocumentJob, DocumentJobState


class _FixedIds:
    def new_id(self) -> str:
        return "a" * 32


class _FakeJobs:
    def __init__(self) -> None:
        self.job: DocumentJob | None = None
        self.transitions: list[tuple[DocumentJobState, DocumentJobState]] = []

    async def create(self, job: DocumentJob) -> None:
        self.job = job

    async def get(self, job_id: str) -> DocumentJob | None:
        return self.job

    async def transition(
        self,
        job_id: str,
        expected: DocumentJobState,
        target: DocumentJobState,
    ) -> DocumentJob:
        self.transitions.append((expected, target))
        assert self.job is not None
        self.job = self.job.transition(target)
        return self.job


class _FakeArtifacts:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.initialized = False

    async def initialize(self, job: DocumentJob, definition: CreateDocumentJobDto) -> None:
        if self.fail:
            raise revision_error("IO_FAILURE")
        self.initialized = True

    async def write_json_once(
        self,
        job_id: str,
        relative_path: str,
        value: object,
    ) -> str:
        raise NotImplementedError

    async def read_json(self, job_id: str, relative_path: str) -> dict[str, object]:
        raise NotImplementedError


def _request() -> CreateDocumentJobDto:
    return CreateDocumentJobDto(
        "/approved/source",
        "운영 가이드를 작성합니다.",
        "integrated.md",
        "b" * 64,
    )


class CreateDocumentJobTest(unittest.TestCase):
    def test_creates_job_and_initializes_artifacts(self) -> None:
        jobs = _FakeJobs()
        artifacts = _FakeArtifacts()
        result = asyncio.run(CreateDocumentJob(jobs, artifacts, _FixedIds()).execute(_request()))
        self.assertEqual(result.job_id, "job-" + "a" * 32)
        self.assertEqual(result.state, DocumentJobState.CREATED)
        self.assertTrue(artifacts.initialized)
        self.assertEqual(jobs.transitions, [])

    def test_marks_job_failed_when_artifact_initialization_fails(self) -> None:
        jobs = _FakeJobs()
        use_case = CreateDocumentJob(jobs, _FakeArtifacts(fail=True), _FixedIds())
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(use_case.execute(_request()))
        self.assertEqual(captured.exception.code, "IO_FAILURE")
        self.assertEqual(
            jobs.transitions,
            [(DocumentJobState.CREATED, DocumentJobState.FAILED)],
        )

    def test_rejects_invalid_job_definition(self) -> None:
        with self.assertRaises(ValueError):
            CreateDocumentJobDto("relative", "instruction", "output.md", "b" * 64)
        with self.assertRaises(ValueError):
            CreateDocumentJobDto("/source", " ", "output.md", "b" * 64)
        with self.assertRaises(ValueError):
            CreateDocumentJobDto("/source", "instruction", "../output.md", "b" * 64)


if __name__ == "__main__":
    unittest.main()
