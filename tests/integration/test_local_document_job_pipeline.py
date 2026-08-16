from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from enterprise_rag.application.dto.job_dashboard import CheckpointStatus
from enterprise_rag.application.dto.job_result import (
    CompletionNotificationState,
    JobResultAvailability,
)
from enterprise_rag.application.dto.jobs import (
    CreateDocumentJobDto,
    JobExecutionSettingsDto,
)
from enterprise_rag.application.dto.long_document import ChunkingConfigDto
from enterprise_rag.application.use_cases.get_document_job_result import (
    GetDocumentJobResult,
)
from enterprise_rag.application.use_cases.notify_document_job_completion import (
    NotifyDocumentJobCompletion,
)
from enterprise_rag.application.use_cases.run_document_job import RunDocumentJob
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.jobs import DocumentJob, DocumentJobState
from enterprise_rag.infrastructure.chunking.structure_aware_text_chunker import (
    StructureAwareTextChunker,
)
from enterprise_rag.infrastructure.jobs.filesystem_claim_draft_repository import (
    FilesystemClaimDraftRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_claim_ledger_repository import (
    FilesystemClaimLedgerRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_completion_notification_repository import (
    FilesystemCompletionNotificationRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_document_job_result_reader import (
    FilesystemDocumentJobResultReader,
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
from enterprise_rag.infrastructure.jobs.filesystem_model_stream_repository import (
    FilesystemModelStreamRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_task_plan_repository import (
    FilesystemTaskPlanRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_task_result_repository import (
    FilesystemTaskResultRepository,
)
from enterprise_rag.infrastructure.jobs.filesystem_web_research_repository import (
    FilesystemWebResearchRepository,
)
from enterprise_rag.infrastructure.jobs.local_document_job_stages import (
    LocalDocumentJobStages,
)
from enterprise_rag.infrastructure.models.observed_text_generator import (
    ObservedTextGenerator,
)
from enterprise_rag.infrastructure.models.structured_claim_draft_generator import (
    StructuredClaimDraftGenerator,
)
from enterprise_rag.infrastructure.models.structured_claim_relation_generator import (
    StructuredClaimRelationGenerator,
)
from enterprise_rag.infrastructure.models.structured_task_definition_generator import (
    StructuredTaskDefinitionGenerator,
)
from enterprise_rag.infrastructure.models.structured_task_output_generator import (
    StructuredTaskOutputGenerator,
)
from enterprise_rag.infrastructure.persistence.sqlite_document_job_repository import (
    SqliteDocumentJobRepository,
)
from enterprise_rag.infrastructure.sources.before_text_source import BeforeTextDocumentSource
from enterprise_rag.infrastructure.tokenization.conservative_utf8 import (
    ConservativeUtf8TokenCounter,
)
from enterprise_rag.infrastructure.workspace.file_io import sha256_file
from enterprise_rag.infrastructure.workspace.folder_revision_workspace import (
    FolderRevisionWorkspace,
)
from enterprise_rag.infrastructure.workspace.folder_tree_comparator import (
    FolderTreeComparator,
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
            return json.dumps({"relations": [], "completion_marker": "RELATIONS_COMPLETE"})
        if "TASK_PLAN_COMPLETE" in user_prompt:
            return json.dumps(
                {
                    "tasks": [
                        {
                            "task_id": "operations-guide",
                            "title": "운영 개요",
                            "objective": "검증된 운영 사실을 정리한다.",
                            "owned_claim_refs": [claim["claim_ref"] for claim in payload["claims"]],
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
            evidence_refs = list(task["allowed_evidence_refs"])
            markers = " ".join(f"[evidence:{item}]" for item in evidence_refs)
            return json.dumps(
                {
                    "task_id": task["task_id"],
                    "sections": [
                        {
                            "section_key": "overview",
                            "heading": "검증된 운영 사실",
                            "markdown": f"운영 사실을 정리한다. {markers}",
                            "used_claim_refs": list(task["owned_claim_refs"]),
                            "used_evidence_refs": evidence_refs,
                        }
                    ],
                    "conflict_claim_refs": [],
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


class _Notifier:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def send(self, title: str, message: str) -> None:
        self.messages.append((title, message))


class LocalDocumentJobPipelineTest(unittest.TestCase):
    def test_rejects_nested_output_before_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source_root = Path(temporary).resolve() / "source"
            source_root.mkdir()
            nested_output = source_root / "must-not-be-created"

            with self.assertRaises(ApplicationError) as captured:
                LocalDocumentJobStages._prepare_output_root(
                    source_root,
                    nested_output,
                )

            self.assertEqual(captured.exception.code, "BEFORE_AFTER_OVERLAP")
            self.assertFalse(nested_output.exists())

    def test_runs_real_stage_adapters_and_publishes_only_after_quality_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source_root = root / "source"
            output_root = root / "output"
            source_root.mkdir()
            (source_root / "guide.md").write_text(
                "# 운영 가이드\n\n서비스 상태를 매일 확인한다.\n",
                encoding="utf-8",
            )
            clock = _Clock()
            jobs = SqliteDocumentJobRepository(root / "var/metadata.sqlite3", clock)
            artifacts = FilesystemJobArtifactRepository(root / "var")
            evidence = FilesystemEvidenceRepository(artifacts)
            claims = FilesystemClaimLedgerRepository(artifacts)
            claim_drafts = FilesystemClaimDraftRepository(artifacts)
            plans = FilesystemTaskPlanRepository(artifacts)
            results = FilesystemTaskResultRepository(artifacts)
            finals = FilesystemFinalDocumentRepository(artifacts)
            web_research = FilesystemWebResearchRepository(artifacts)
            model_streams = FilesystemModelStreamRepository(root / "var")
            stream_ids = _Ids()
            job = DocumentJob("job-" + "1" * 32)
            execution = JobExecutionSettingsDto(
                str(output_root),
                "local/test-model",
                "a" * 40,
                16_384,
                12_000,
                "운영 절차를 먼저 배치한다.",
                "b" * 64,
                2,
                True,
                True,
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
            stage_budgets: dict[str, tuple[int, str]] = {}

            def claim_draft_factory(generator, budget, additional):
                stage_budgets["claim_draft"] = (budget, additional)
                return StructuredClaimDraftGenerator(generator, budget, additional)

            def claim_relation_factory(generator, budget, additional):
                stage_budgets["claim_relation"] = (budget, additional)
                return StructuredClaimRelationGenerator(generator, budget, additional)

            def task_definition_factory(generator, budget, additional):
                stage_budgets["task_plan"] = (budget, additional)
                return StructuredTaskDefinitionGenerator(generator, budget, additional)

            def task_output_factory(generator, budget, additional):
                stage_budgets["task_output"] = (budget, additional)
                return StructuredTaskOutputGenerator(generator, budget, additional)

            stages = LocalDocumentJobStages(
                artifacts,
                FilesystemDocumentJobDefinitionRepository(artifacts),
                evidence,
                claims,
                plans,
                results,
                finals,
                ChunkingConfigDto("conservative-utf8-bytes-v1", "1", 800, 1_200, 80, 0.1),
                claim_drafts=claim_drafts,
                chunker=StructureAwareTextChunker(ConservativeUtf8TokenCounter()),
                source_factory=lambda path: BeforeTextDocumentSource(path, 1_000_000),
                workspace_factory=lambda before, after: FolderRevisionWorkspace(
                    before,
                    after,
                    FolderTreeComparator(),
                    clock,
                    _Ids(),
                    1_000_000,
                ),
                model_factory=lambda _: _StructuredGenerator(),
                observed_generator_factory=lambda generator, job_id, stage: ObservedTextGenerator(
                    generator,
                    job_id,
                    stage,
                    model_streams,
                    clock,
                    stream_ids,
                ),
                claim_draft_generator_factory=claim_draft_factory,
                claim_relation_generator_factory=claim_relation_factory,
                task_definition_generator_factory=task_definition_factory,
                task_output_generator_factory=task_output_factory,
                file_digest=sha256_file,
                web_research=web_research,
            ).stages()

            self.assertFalse(output_root.exists())
            asyncio.run(stages[0].execute(job.job_id))
            self.assertTrue(output_root.is_dir())

            completed = asyncio.run(RunDocumentJob(jobs, jobs, stages).execute(job.job_id))
            self.assertEqual(completed.state, DocumentJobState.COMPLETED)
            self.assertEqual(completed.last_percentage, 100)
            self.assertEqual(stage_budgets["claim_draft"][0], 2_048)
            self.assertEqual(stage_budgets["claim_relation"], (2_048, ""))
            self.assertEqual(stage_budgets["task_plan"][0], 4_096)
            self.assertEqual(stage_budgets["task_output"][0], 8_192)
            self.assertEqual(len(asyncio.run(jobs.list_after(job.job_id))), 10)
            stream = asyncio.run(model_streams.snapshot(job.job_id))
            self.assertEqual(
                {event.stage for event in stream.events if event.text},
                {"CLAIM_DRAFT", "TASK_PLAN", "TASK_OUTPUT"},
            )
            self.assertTrue(asyncio.run(artifacts.list_relative_paths(job.job_id, "claim-drafts")))
            published = output_root / "runs" / job.job_id
            self.assertTrue((published / "documents/generated.md").is_file())
            self.assertTrue((published / "_reports/comparison.json").is_file())
            publish_result = asyncio.run(
                artifacts.read_json(job.job_id, "control/publish-result.json")
            )
            self.assertEqual(publish_result["run_id"], job.job_id)
            observations = asyncio.run(
                artifacts.read_json(job.job_id, "control/document-observations.json")
            )
            self.assertEqual(observations["mode"], "NON_BLOCKING_OBSERVATION")
            self.assertTrue(observations["retrieval_units"])
            web_report = asyncio.run(web_research.load(job.job_id))
            self.assertEqual(web_report.status, "DISABLED")
            checkpoints = FilesystemJobCheckpointInspector(
                artifacts,
                evidence,
                claims,
                plans,
                results,
                finals,
                claim_drafts,
            )
            inspected = {
                item.checkpoint_id: item for item in asyncio.run(checkpoints.inspect(job.job_id))
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
            definitions = FilesystemDocumentJobDefinitionRepository(artifacts)
            reader = FilesystemDocumentJobResultReader(
                root / "var",
                artifacts,
                definitions,
                finals,
            )
            result = asyncio.run(GetDocumentJobResult(jobs, reader).execute(job.job_id))
            self.assertEqual(result.availability, JobResultAvailability.PUBLISHED)
            self.assertEqual(result.document_path, str(published / "documents/generated.md"))
            self.assertTrue(result.quality.valid)
            self.assertEqual(result.comparison_counts.total, 2)

            receipts = FilesystemCompletionNotificationRepository(root / "var")
            notifier = _Notifier()
            notifications = NotifyDocumentJobCompletion(
                jobs,
                reader,
                receipts,
                notifier,
                clock,
            )
            first = asyncio.run(notifications.execute(job.job_id))
            repeated = asyncio.run(notifications.execute(job.job_id))
            self.assertEqual(first.state, CompletionNotificationState.DELIVERED)
            self.assertEqual(repeated, first)
            self.assertEqual(len(notifier.messages), 1)
            self.assertTrue(
                (root / "var/jobs" / job.job_id / "control/completion-notification.json").is_file()
            )

            comparison_path = published / "_reports/comparison.json"
            comparison_path.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(GetDocumentJobResult(jobs, reader).execute(job.job_id))
            self.assertEqual(captured.exception.code, "JOB_RESULT_INVALID")


if __name__ == "__main__":
    unittest.main()
