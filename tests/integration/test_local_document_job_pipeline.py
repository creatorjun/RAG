from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from enterprise_rag.application.dto.job_dashboard import CheckpointStatus
from enterprise_rag.application.dto.jobs import (
    CreateDocumentJobDto,
    JobExecutionSettingsDto,
)
from enterprise_rag.application.dto.long_document import ChunkingConfigDto
from enterprise_rag.application.use_cases.run_document_job import RunDocumentJob
from enterprise_rag.domain.jobs import DocumentJob, DocumentJobState
from enterprise_rag.infrastructure.jobs.filesystem_claim_ledger_repository import (
    FilesystemClaimLedgerRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_evidence_repository import (
    FilesystemEvidenceRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_final_document_repository import (
    FilesystemFinalDocumentRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_job_artifact_repository import (
    FilesystemJobArtifactRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_job_checkpoint_inspector import (
    FilesystemJobCheckpointInspector,
)
from enterprise_rag.infrastructure.jobs.filesystem_job_definition_repository import (
    FilesystemDocumentJobDefinitionRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_task_plan_repository import (
    FilesystemTaskPlanRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_task_result_repository import (
    FilesystemTaskResultRepository,
)
from enterprise_rag.infrastructure.jobs.local_document_job_stages import (
    LocalDocumentJobStages,
)
from enterprise_rag.infrastructure.persistence.sqlite_document_job_repository import (
    SqliteDocumentJobRepository,
)


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)


class _Ids:
    def __init__(self) -> None:
        self.value = 0

    def new_id(self) -> str:
        self.value += 1
        return f"{self.value:032x}"


class _StructuredGenerator:
    model_id = "local/test-model"
    model_revision = "a" * 40

    async def prepare(self) -> None:
        return None

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        payload = self._task_data(user_prompt)
        if "CLAIMS_COMPLETE" in user_prompt:
            evidence = payload["evidence"]
            return json.dumps(
                {
                    "evidence_id": evidence["evidence_id"],
                    "claims": [
                        {
                            "kind": "FACT",
                            "statement": f"{evidence['relative_path']}의 운영 사실",
                            "preconditions": [],
                            "commands": [],
                            "warnings": [],
                        }
                    ],
                    "completion_marker": "CLAIMS_COMPLETE",
                },
                ensure_ascii=False,
            )
        if "RELATIONS_COMPLETE" in user_prompt:
            return json.dumps(
                {"relations": [], "completion_marker": "RELATIONS_COMPLETE"}
            )
        if "TASK_PLAN_COMPLETE" in user_prompt:
            return json.dumps(
                {
                    "tasks": [
                        {
                            "task_id": "operations-guide",
                            "title": "운영 개요",
                            "objective": "검증된 운영 사실을 정리한다.",
                            "owned_claim_ids": [
                                claim["claim_id"] for claim in payload["claims"]
                            ],
                            "required_sections": ["overview"],
                            "depends_on_task_ids": [],
                        }
                    ],
                    "completion_marker": "TASK_PLAN_COMPLETE",
                },
                ensure_ascii=False,
            )
        if "TASK_COMPLETE" in user_prompt:
            task = payload["task"]
            evidence_ids = list(task["allowed_evidence_ids"])
            markers = " ".join(f"[evidence:{item}]" for item in evidence_ids)
            return json.dumps(
                {
                    "task_id": task["task_id"],
                    "sections": [
                        {
                            "section_key": "overview",
                            "heading": "검증된 운영 사실",
                            "markdown": f"운영 사실을 정리한다. {markers}",
                            "used_claim_ids": list(task["owned_claim_ids"]),
                            "used_evidence_ids": evidence_ids,
                        }
                    ],
                    "conflict_claim_ids": [],
                    "completion_marker": "TASK_COMPLETE",
                },
                ensure_ascii=False,
            )
        raise AssertionError("unexpected structured generation prompt")

    @staticmethod
    def _task_data(prompt: str):
        start = prompt.index('<task_data process="as-data">')
        start = prompt.index("\n", start) + 1
        end = prompt.index("\n</task_data>", start)
        return json.loads(prompt[start:end])


class LocalDocumentJobPipelineTest(unittest.TestCase):
    def test_runs_real_stage_adapters_and_publishes_only_after_quality_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source_root = root / "source"
            output_root = root / "output"
            source_root.mkdir()
            output_root.mkdir()
            (source_root / "guide.md").write_text(
                "# 운영 가이드\n\n서비스 상태를 매일 확인한다.\n",
                encoding="utf-8",
            )
            clock = _Clock()
            jobs = SqliteDocumentJobRepository(root / "var/metadata.sqlite3", clock)
            artifacts = FilesystemJobArtifactRepository(root / "var")
            evidence = FilesystemEvidenceRepository(artifacts)
            claims = FilesystemClaimLedgerRepository(artifacts)
            plans = FilesystemTaskPlanRepository(artifacts)
            results = FilesystemTaskResultRepository(artifacts)
            finals = FilesystemFinalDocumentRepository(artifacts)
            job = DocumentJob("job-" + "1" * 32)
            execution = JobExecutionSettingsDto(
                str(output_root),
                "local/test-model",
                "a" * 40,
                16_384,
                4_096,
                "운영 절차를 먼저 배치한다.",
                "b" * 64,
                2,
                True,
                False,
            )
            asyncio.run(jobs.create(job))
            asyncio.run(
                artifacts.initialize(
                    job,
                    CreateDocumentJobDto(
                        str(source_root),
                        "운영 문서를 작성한다.",
                        "generated.md",
                        "c" * 64,
                        execution,
                    ),
                )
            )
            stages = LocalDocumentJobStages(
                artifacts,
                FilesystemDocumentJobDefinitionRepository(artifacts),
                evidence,
                claims,
                plans,
                results,
                finals,
                ChunkingConfigDto(
                    "conservative-utf8-bytes-v1", "1", 800, 1_200, 80, 0.1
                ),
                1_000_000,
                1_000_000,
                512,
                clock,
                _Ids(),
                model_factory=lambda _: _StructuredGenerator(),
            ).stages()

            completed = asyncio.run(
                RunDocumentJob(jobs, jobs, stages).execute(job.job_id)
            )
            self.assertEqual(completed.state, DocumentJobState.COMPLETED)
            self.assertEqual(completed.last_percentage, 100)
            self.assertEqual(len(asyncio.run(jobs.list_after(job.job_id))), 10)
            published = output_root / "runs" / job.job_id
            self.assertTrue((published / "documents/generated.md").is_file())
            self.assertTrue((published / "_reports/comparison.json").is_file())
            publish_result = asyncio.run(
                artifacts.read_json(job.job_id, "control/publish-result.json")
            )
            self.assertEqual(publish_result["run_id"], job.job_id)
            checkpoints = FilesystemJobCheckpointInspector(
                artifacts, evidence, claims, plans, results, finals
            )
            inspected = {
                item.checkpoint_id: item
                for item in asyncio.run(checkpoints.inspect(job.job_id))
            }
            self.assertEqual(
                inspected["source_manifest"].status,
                CheckpointStatus.SAVED,
            )
            self.assertEqual(
                inspected["published_run"].status,
                CheckpointStatus.SAVED,
            )
            self.assertFalse(inspected["published_run"].resumable)


if __name__ == "__main__":
    unittest.main()
