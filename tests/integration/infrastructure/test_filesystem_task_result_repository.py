from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from enterprise_rag.application.dto.jobs import CreateDocumentJobDto
from enterprise_rag.application.dto.tasks import (
    TaskOutputDto,
    TaskSectionOutputDto,
    TaskValidationReportDto,
)
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJob
from enterprise_rag.infrastructure.jobs.filesystem_job_artifact_repository import (
    FilesystemJobArtifactRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_task_result_repository import (
    FilesystemTaskResultRepository,
)


class FilesystemTaskResultRepositoryTest(unittest.TestCase):
    def test_round_trips_attempt_output_and_validation_as_write_once_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            artifacts = FilesystemJobArtifactRepository(root / "var")
            job = DocumentJob("job-" + "a" * 32)
            asyncio.run(
                artifacts.initialize(
                    job,
                    CreateDocumentJobDto(
                        str(root), "문서 작성", "output.md", "b" * 64
                    ),
                )
            )
            evidence_id = "evidence:sha256:" + "c" * 64
            claim_id = "claim:sha256:" + "d" * 64
            output = TaskOutputDto(
                "service-task",
                (
                    TaskSectionOutputDto(
                        "절차",
                        "표준 절차",
                        f"서비스를 시작한다. [evidence:{evidence_id}]",
                        (claim_id,),
                        (evidence_id,),
                    ),
                ),
                (),
                "TASK_COMPLETE",
            )
            report = TaskValidationReportDto(output.task_id, True, ())
            repository = FilesystemTaskResultRepository(artifacts)

            output_path = asyncio.run(repository.save_output(job.job_id, 1, output))
            validation_path = asyncio.run(
                repository.save_validation(job.job_id, 1, report)
            )

            self.assertEqual(
                output_path,
                "tasks/service-task/attempt-001/output.json",
            )
            self.assertEqual(
                validation_path,
                "tasks/service-task/attempt-001/validation.json",
            )
            self.assertEqual(
                asyncio.run(repository.load_output(job.job_id, output.task_id, 1)),
                output,
            )
            self.assertEqual(
                asyncio.run(repository.load_validation(job.job_id, output.task_id, 1)),
                report,
            )
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.save_output(job.job_id, 1, output))
            self.assertEqual(captured.exception.code, "JOB_ARTIFACT_ALREADY_EXISTS")

    def test_rejects_invalid_attempt_before_building_artifact_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = FilesystemTaskResultRepository(
                FilesystemJobArtifactRepository(Path(temporary).resolve() / "var")
            )
            output = TaskOutputDto(
                "service-task",
                (TaskSectionOutputDto("a", "a", "a", ("c",), ("e",)),),
                (),
                "TASK_COMPLETE",
            )
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(repository.save_output("job-" + "a" * 32, 0, output))
            self.assertEqual(captured.exception.code, "TASK_OUTPUT_INVALID")


if __name__ == "__main__":
    unittest.main()
