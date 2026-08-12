from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from enterprise_rag.application.dto.jobs import CreateDocumentJobDto
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.jobs.filesystem_job_artifact_repository import (
    FilesystemJobArtifactRepository,
)


class FilesystemJobArtifactRepositoryTest(unittest.TestCase):
    @staticmethod
    def _definition(root: Path) -> CreateDocumentJobDto:
        return CreateDocumentJobDto(
            str(root),
            "통합 문서 작성",
            "integrated.md",
            "b" * 64,
        )

    def test_initializes_and_writes_immutable_nested_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            var_root = Path(temporary).resolve() / "var"
            repository = FilesystemJobArtifactRepository(var_root)
            job = DocumentJob("job-" + "a" * 32)
            asyncio.run(repository.initialize(job, self._definition(Path(temporary).resolve())))
            written = asyncio.run(
                repository.write_json_once(
                    job.job_id,
                    "tasks/security/request.json",
                    {"schema_version": 1, "task_id": "security"},
                )
            )
            value = asyncio.run(
                repository.read_json(job.job_id, "tasks/security/request.json")
            )
            self.assertEqual(written, "tasks/security/request.json")
            self.assertEqual(value["task_id"], "security")
            self.assertTrue((var_root / "jobs" / job.job_id / "job.json").is_file())
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(
                    repository.write_json_once(
                        job.job_id,
                        "tasks/security/request.json",
                        {"task_id": "replacement"},
                    )
                )
            self.assertEqual(captured.exception.code, "JOB_ARTIFACT_ALREADY_EXISTS")

    def test_rejects_duplicate_job_escape_and_invalid_job_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = FilesystemJobArtifactRepository(Path(temporary).resolve() / "var")
            job = DocumentJob("job-" + "b" * 32)
            definition = self._definition(Path(temporary).resolve())
            asyncio.run(repository.initialize(job, definition))
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.initialize(job, definition))
            self.assertEqual(captured.exception.code, "JOB_ARTIFACT_ALREADY_EXISTS")
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.write_json_once(job.job_id, "../escape.json", {}))
            self.assertEqual(captured.exception.code, "PATH_ESCAPE")
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.read_json("invalid", "job.json"))
            self.assertEqual(captured.exception.code, "INVALID_JOB_ID")

    def test_rejects_symlink_in_artifact_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            var_root = Path(temporary).resolve() / "var"
            repository = FilesystemJobArtifactRepository(var_root)
            job = DocumentJob("job-" + "c" * 32)
            asyncio.run(repository.initialize(job, self._definition(Path(temporary).resolve())))
            outside = Path(temporary).resolve() / "outside"
            outside.mkdir()
            link = var_root / "jobs" / job.job_id / "tasks"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.write_json_once(job.job_id, "tasks/output.json", {}))
            self.assertEqual(captured.exception.code, "LINK_NOT_ALLOWED")


if __name__ == "__main__":
    unittest.main()
