from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from enterprise_rag.application.dto.job_pipeline import JobStageResultDto
from enterprise_rag.application.dto.jobs import StoredDocumentJobDefinitionDto
from enterprise_rag.application.dto.long_document import ChunkingConfigDto, TextDocumentDto
from enterprise_rag.application.dto.revision import (
    GeneratedDocumentWriteDto,
    SourceDocumentRecordDto,
)
from enterprise_rag.application.ports.cancellation import CancellationTokenPort
from enterprise_rag.application.ports.claim_draft_generator import (
    ClaimDraftGeneratorPort,
)
from enterprise_rag.application.ports.claim_ledger_repository import (
    ClaimLedgerRepositoryPort,
)
from enterprise_rag.application.ports.claim_relation_generator import (
    ClaimRelationGeneratorPort,
)
from enterprise_rag.application.ports.document_workspace import DocumentWorkspacePort
from enterprise_rag.application.ports.evidence_repository import EvidenceRepositoryPort
from enterprise_rag.application.ports.final_document_repository import (
    FinalDocumentRepositoryPort,
)
from enterprise_rag.application.ports.job_artifacts import JobArtifactRepositoryPort
from enterprise_rag.application.ports.job_definition_repository import (
    DocumentJobDefinitionRepositoryPort,
)
from enterprise_rag.application.ports.job_stage import DocumentJobStagePort
from enterprise_rag.application.ports.long_document import (
    LongDocumentChunkerPort,
    TextDocumentCollectionPort,
)
from enterprise_rag.application.ports.task_definition_generator import (
    TaskDefinitionGeneratorPort,
)
from enterprise_rag.application.ports.task_output_generator import TaskOutputGeneratorPort
from enterprise_rag.application.ports.task_plan_repository import TaskPlanRepositoryPort
from enterprise_rag.application.ports.task_result_repository import (
    TaskResultRepositoryPort,
)
from enterprise_rag.application.ports.text_generator import TextGeneratorPort
from enterprise_rag.application.progress import ProgressReporter
from enterprise_rag.application.use_cases.assemble_document import AssembleDocument
from enterprise_rag.application.use_cases.build_claim_ledger import BuildClaimLedger
from enterprise_rag.application.use_cases.build_evidence_bundle import BuildEvidenceBundle
from enterprise_rag.application.use_cases.build_final_document_candidate import (
    BuildFinalDocumentCandidate,
)
from enterprise_rag.application.use_cases.build_reviewed_claim_ledger import (
    BuildReviewedClaimLedger,
)
from enterprise_rag.application.use_cases.build_task_plan import BuildTaskPlan
from enterprise_rag.application.use_cases.execute_resumable_task_plan import (
    ExecuteResumableTaskPlan,
)
from enterprise_rag.application.use_cases.execute_task_attempt import ExecuteTaskAttempt
from enterprise_rag.application.use_cases.extract_claim_drafts import ExtractClaimDrafts
from enterprise_rag.application.use_cases.inspect_integration_sources import (
    InspectIntegrationSources,
)
from enterprise_rag.application.use_cases.plan_document_tasks import PlanDocumentTasks
from enterprise_rag.application.use_cases.validate_final_document import (
    ValidateFinalDocument,
)
from enterprise_rag.application.use_cases.validate_task_output import ValidateTaskOutput
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.domain.jobs import DocumentJobState

_PUBLISH_RESULT = "control/publish-result.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CLAIM_DRAFT_OUTPUT_CAP = 2_048
_CLAIM_RELATION_OUTPUT_CAP = 2_048
_TASK_PLAN_OUTPUT_CAP = 4_096
ModelFactory = Callable[[StoredDocumentJobDefinitionDto], TextGeneratorPort]
ClaimDraftGeneratorFactory = Callable[
    [TextGeneratorPort, int, str], ClaimDraftGeneratorPort
]
ClaimRelationGeneratorFactory = Callable[
    [TextGeneratorPort, int, str], ClaimRelationGeneratorPort
]
TaskDefinitionGeneratorFactory = Callable[
    [TextGeneratorPort, int, str], TaskDefinitionGeneratorPort
]
TaskOutputGeneratorFactory = Callable[
    [TextGeneratorPort, int, str], TaskOutputGeneratorPort
]
SourceFactory = Callable[[Path], TextDocumentCollectionPort]
WorkspaceFactory = Callable[[Path, Path], DocumentWorkspacePort]
FileDigest = Callable[[Path], str]


@dataclass(frozen=True, slots=True)
class _Stage:
    state: DocumentJobState
    callback: Callable[[str], Awaitable[JobStageResultDto]]
    cancellation: CancellationTokenPort | None = None

    async def execute(self, job_id: str) -> JobStageResultDto:
        if self.cancellation is not None:
            self.cancellation.raise_if_cancelled()
        result = await self.callback(job_id)
        if self.cancellation is not None:
            self.cancellation.raise_if_cancelled()
        return result


@dataclass(slots=True)
class _Runtime:
    definition: StoredDocumentJobDefinitionDto
    task_execution: ExecuteResumableTaskPlan
    extract_claims: ExtractClaimDrafts
    build_claims: BuildReviewedClaimLedger
    plan_tasks: PlanDocumentTasks


class LocalDocumentJobStages:
    def __init__(
        self,
        artifacts: JobArtifactRepositoryPort,
        definitions: DocumentJobDefinitionRepositoryPort,
        evidence: EvidenceRepositoryPort,
        claims: ClaimLedgerRepositoryPort,
        plans: TaskPlanRepositoryPort,
        results: TaskResultRepositoryPort,
        finals: FinalDocumentRepositoryPort,
        chunking: ChunkingConfigDto,
        *,
        chunker: LongDocumentChunkerPort,
        source_factory: SourceFactory,
        workspace_factory: WorkspaceFactory,
        model_factory: ModelFactory,
        claim_draft_generator_factory: ClaimDraftGeneratorFactory,
        claim_relation_generator_factory: ClaimRelationGeneratorFactory,
        task_definition_generator_factory: TaskDefinitionGeneratorFactory,
        task_output_generator_factory: TaskOutputGeneratorFactory,
        file_digest: FileDigest,
        cancellation: CancellationTokenPort | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._definitions = definitions
        self._evidence = evidence
        self._claims = claims
        self._plans = plans
        self._results = results
        self._finals = finals
        self._chunking = chunking
        self._chunker = chunker
        self._source_factory = source_factory
        self._workspace_factory = workspace_factory
        self._model_factory = model_factory
        self._claim_draft_generator_factory = claim_draft_generator_factory
        self._claim_relation_generator_factory = claim_relation_generator_factory
        self._task_definition_generator_factory = task_definition_generator_factory
        self._task_output_generator_factory = task_output_generator_factory
        self._file_digest = file_digest
        self._cancellation = cancellation
        self._runtimes: dict[str, _Runtime] = {}

    def stages(self) -> tuple[DocumentJobStagePort, ...]:
        return (
            _Stage(DocumentJobState.INSPECTING, self._inspect, self._cancellation),
            _Stage(DocumentJobState.SNAPSHOTTING, self._snapshot, self._cancellation),
            _Stage(
                DocumentJobState.EXTRACTING_EVIDENCE,
                self._extract_evidence,
                self._cancellation,
            ),
            _Stage(
                DocumentJobState.BUILDING_CLAIMS,
                self._build_claim_ledger,
                self._cancellation,
            ),
            _Stage(DocumentJobState.PLANNING, self._plan, self._cancellation),
            _Stage(DocumentJobState.RUNNING_TASKS, self._run_tasks, self._cancellation),
            _Stage(
                DocumentJobState.VALIDATING_TASKS,
                self._validate_tasks,
                self._cancellation,
            ),
            _Stage(DocumentJobState.ASSEMBLING, self._assemble, self._cancellation),
            _Stage(
                DocumentJobState.VALIDATING_FINAL,
                self._validate_final,
                self._cancellation,
            ),
            _Stage(DocumentJobState.PUBLISHING, self._publish, self._cancellation),
        )

    async def _runtime(self, job_id: str) -> _Runtime:
        existing = self._runtimes.get(job_id)
        if existing is not None:
            return existing
        definition = await self._definitions.load(job_id)
        execution = definition.request.execution_settings
        if execution is None:
            raise revision_error("JOB_DEFINITION_INVALID", {"job_id": job_id})
        generator = self._model_factory(definition)
        output_budget = execution.max_output_tokens
        additional = execution.additional_system_prompt
        result_writer = self._task_output_generator_factory(
            generator, output_budget, additional
        )
        attempts = ExecuteTaskAttempt(
            result_writer,
            self._results,
            ValidateTaskOutput(),
        )
        runtime = _Runtime(
            definition=definition,
            task_execution=ExecuteResumableTaskPlan(
                attempts,
                self._results,
                execution.max_task_attempts,
            ),
            extract_claims=ExtractClaimDrafts(
                self._claim_draft_generator_factory(
                    generator,
                    min(output_budget, _CLAIM_DRAFT_OUTPUT_CAP),
                    additional,
                )
            ),
            build_claims=BuildReviewedClaimLedger(
                # Claim drafts already reflect the user's extraction scope. Repeating
                # the final-document formatting prompt here only consumes relation
                # context and cannot change the fixed relation JSON contract.
                self._claim_relation_generator_factory(
                    generator,
                    min(output_budget, _CLAIM_RELATION_OUTPUT_CAP),
                    "",
                ),
                BuildClaimLedger(),
            ),
            plan_tasks=PlanDocumentTasks(
                self._task_definition_generator_factory(
                    generator,
                    min(output_budget, _TASK_PLAN_OUTPUT_CAP),
                    additional,
                ),
                BuildTaskPlan(),
            ),
        )
        self._runtimes[job_id] = runtime
        return runtime

    async def _inspect(self, job_id: str) -> JobStageResultDto:
        runtime = await self._runtime(job_id)
        source = self._source(runtime.definition)
        documents = await self._read_documents(source)
        value: dict[str, object] = {
            "schema_version": 1,
            "job_id": job_id,
            "pipeline_fingerprint": runtime.definition.request.pipeline_fingerprint,
            "source_root": runtime.definition.request.source_root,
            "files": [self._document_record(document) for document in documents],
        }
        await self._write_or_verify_json(job_id, "source-manifest.json", value)
        return JobStageResultDto(
            "원본 manifest를 고정했습니다.", len(documents), len(documents), "documents"
        )

    async def _snapshot(self, job_id: str) -> JobStageResultDto:
        runtime = await self._runtime(job_id)
        expected = await self._source_manifest(job_id, runtime.definition)
        current = await self._read_documents(self._source(runtime.definition))
        records = tuple(self._document_record(document) for document in current)
        if records != expected:
            raise revision_error("INPUT_HASH_CHANGED", {"job_id": job_id})
        return JobStageResultDto(
            "원본 snapshot hash를 재검증했습니다.", len(records), len(records), "documents"
        )

    async def _extract_evidence(self, job_id: str) -> JobStageResultDto:
        existing = await self._load_optional(self._evidence.load, job_id)
        if existing is not None:
            return JobStageResultDto(
                "저장된 Evidence를 복원했습니다.",
                len(existing.items),
                existing.source_structure_count,
                "evidence",
            )
        runtime = await self._runtime(job_id)
        source = self._source(runtime.definition)
        integration_input = await InspectIntegrationSources(
            source,
            self._chunker,
            self._chunking,
        ).execute(ProgressReporter())
        expected = await self._source_manifest(job_id, runtime.definition)
        if tuple(self._document_record(item) for item in integration_input.documents) != expected:
            raise revision_error("INPUT_HASH_CHANGED", {"job_id": job_id})
        bundle = BuildEvidenceBundle().execute(integration_input)
        await self._evidence.save(job_id, bundle)
        return JobStageResultDto(
            "Evidence 추출과 coverage 검증을 완료했습니다.",
            len(bundle.items),
            bundle.source_structure_count,
            "evidence",
        )

    async def _build_claim_ledger(self, job_id: str) -> JobStageResultDto:
        existing = await self._load_optional(self._claims.load, job_id)
        if existing is not None:
            return JobStageResultDto(
                "저장된 Claim Ledger를 복원했습니다.",
                len(existing.claims),
                len(existing.claims),
                "claims",
            )
        runtime = await self._runtime(job_id)
        evidence = await self._evidence.load(job_id)
        instruction = runtime.definition.request.instruction
        drafts = await runtime.extract_claims.execute(evidence, instruction)
        ledger = await runtime.build_claims.execute(evidence, drafts, instruction)
        await self._claims.save(job_id, ledger)
        return JobStageResultDto(
            "Claim 추출·중복 관계 판정을 완료했습니다.",
            len(ledger.claims),
            len(ledger.claims),
            "claims",
        )

    async def _plan(self, job_id: str) -> JobStageResultDto:
        existing = await self._load_optional(self._plans.load, job_id)
        if existing is not None:
            return JobStageResultDto(
                "저장된 Task plan을 복원했습니다.",
                len(existing.tasks),
                len(existing.tasks),
                "tasks",
            )
        runtime = await self._runtime(job_id)
        evidence = await self._evidence.load(job_id)
        ledger = await self._claims.load(job_id)
        plan = await runtime.plan_tasks.execute(
            ledger,
            evidence,
            runtime.definition.request.instruction,
        )
        await self._plans.save(job_id, plan)
        return JobStageResultDto(
            "Claim 단일 소유와 Evidence coverage를 검증해 Task plan을 확정했습니다.",
            len(plan.tasks),
            len(plan.tasks),
            "tasks",
        )

    async def _run_tasks(self, job_id: str) -> JobStageResultDto:
        runtime = await self._runtime(job_id)
        plan = await self._plans.load(job_id)
        ledger = await self._claims.load(job_id)
        evidence = await self._evidence.load(job_id)
        execution = await runtime.task_execution.execute(
            job_id, plan, ledger, evidence
        )
        valid = sum(report.valid for report in execution.validations)
        return JobStageResultDto(
            "Task 생성과 attempt 체크포인트 저장을 완료했습니다.",
            valid,
            len(plan.tasks),
            "validated_tasks",
        )

    async def _validate_tasks(self, job_id: str) -> JobStageResultDto:
        runtime = await self._runtime(job_id)
        plan = await self._plans.load(job_id)
        execution = await runtime.task_execution.load(job_id, plan)
        valid = sum(report.valid for report in execution.validations)
        return JobStageResultDto(
            (
                "모든 Task 품질 검증을 통과했습니다."
                if execution.complete
                else "일부 Task가 최대 재작성 후에도 품질 검증을 통과하지 못했습니다."
            ),
            valid,
            len(plan.tasks),
            "validated_tasks",
            needs_attention=not execution.complete,
        )

    async def _assemble(self, job_id: str) -> JobStageResultDto:
        report = await self._load_optional(
            self._artifacts.read_json, job_id, "control/final-validation.json"
        )
        if report is not None:
            await self._finals.load(job_id)
            return JobStageResultDto("저장된 조립 초안을 복원했습니다.", 1, 1, "drafts")
        runtime = await self._runtime(job_id)
        plan = await self._plans.load(job_id)
        ledger = await self._claims.load(job_id)
        evidence = await self._evidence.load(job_id)
        execution = await runtime.task_execution.load(job_id, plan)
        candidate = BuildFinalDocumentCandidate(
            AssembleDocument(), ValidateFinalDocument()
        ).execute(
            self._title(runtime.definition),
            plan,
            ledger,
            evidence,
            execution,
        )
        await self._finals.save(job_id, candidate)
        return JobStageResultDto("검증된 Task를 결정적으로 조립했습니다.", 1, 1, "drafts")

    async def _validate_final(self, job_id: str) -> JobStageResultDto:
        candidate = await self._finals.load(job_id)
        quality = candidate.quality
        return JobStageResultDto(
            (
                "최종 Claim·Evidence·source 품질 게이트를 통과했습니다."
                if quality.valid
                else "최종 문서가 품질 게이트를 통과하지 못했습니다."
            ),
            quality.validated_task_count,
            max(1, quality.task_count),
            "validated_tasks",
            needs_attention=not quality.valid,
        )

    async def _publish(self, job_id: str) -> JobStageResultDto:
        existing = await self._load_optional(self._artifacts.read_json, job_id, _PUBLISH_RESULT)
        if existing is not None:
            report_digest = existing.get("comparison_report_sha256")
            if (
                existing.get("schema_version") != 1
                or existing.get("job_id") != job_id
                or existing.get("run_id") != job_id
                or not isinstance(report_digest, str)
                or not _SHA256.fullmatch(report_digest)
            ):
                raise revision_error("FINAL_QUALITY_GATE_FAILED", {"job_id": job_id})
            count = self._integer(existing.get("file_count"))
            return JobStageResultDto(
                "저장된 게시 run을 복원했습니다.", count, max(1, count), "files"
            )
        runtime = await self._runtime(job_id)
        execution_settings = runtime.definition.request.execution_settings
        if execution_settings is None:
            raise revision_error("JOB_DEFINITION_INVALID", {"job_id": job_id})
        candidate = await self._finals.load(job_id)
        if not candidate.quality.valid:
            raise revision_error("FINAL_QUALITY_GATE_FAILED", {"job_id": job_id})
        evidence = await self._evidence.load(job_id)
        workspace = self._workspace_factory(
            Path(runtime.definition.request.source_root),
            Path(execution_settings.output_root),
        )
        try:
            await workspace.prepare_run(job_id)
        except ApplicationError as error:
            if error.code != "RUN_ALREADY_EXISTS":
                raise
        await self._write_or_verify_output(
            workspace,
            runtime.definition,
            candidate.markdown,
            evidence.items,
        )
        comparison = await workspace.compare_run(job_id)
        run_root = Path(execution_settings.output_root) / "runs" / job_id
        document_path = (
            run_root
            / "documents"
            / runtime.definition.request.output_relative_path
        )
        comparison_markdown_path = run_root / "_reports/comparison.md"
        synthesis_report_path = run_root / "_reports/synthesis.json"
        value: dict[str, object] = {
            "schema_version": 1,
            "job_id": job_id,
            "run_id": job_id,
            "output_relative_path": runtime.definition.request.output_relative_path,
            "comparison_report_sha256": comparison.report_sha256,
            "file_count": len(comparison.files),
            "counts": comparison.counts,
            "document_sha256": self._file_sha256(document_path),
            "comparison_markdown_sha256": self._file_sha256(
                comparison_markdown_path
            ),
            "synthesis_report_sha256": self._file_sha256(synthesis_report_path),
        }
        await self._write_or_verify_json(job_id, _PUBLISH_RESULT, value)
        return JobStageResultDto(
            "품질 게이트를 통과한 문서를 신규 검토 run에 게시했습니다.",
            len(comparison.files),
            max(1, len(comparison.files)),
            "files",
        )

    def _file_sha256(self, path: Path) -> str:
        try:
            return self._file_digest(path)
        except OSError as error:
            raise revision_error("FINAL_QUALITY_GATE_FAILED") from error

    async def _write_or_verify_output(
        self,
        workspace: DocumentWorkspacePort,
        definition: StoredDocumentJobDefinitionDto,
        markdown: str,
        evidence_items: tuple[Any, ...],
    ) -> None:
        execution = definition.request.execution_settings
        if execution is None:
            raise revision_error("JOB_DEFINITION_INVALID", {"job_id": definition.job_id})
        sources_by_path = {
            item.relative_path: item.source_sha256 for item in evidence_items
        }
        request = GeneratedDocumentWriteDto(
            definition.request.output_relative_path,
            markdown,
            execution.model_id,
            execution.model_revision,
            tuple(
                SourceDocumentRecordDto(path, digest)
                for path, digest in sorted(sources_by_path.items())
            ),
            len(evidence_items),
            len(evidence_items) + 2,
        )
        try:
            await workspace.write_generated_document(definition.job_id, request)
        except ApplicationError as error:
            if error.code != "OUTPUT_ALREADY_EXISTS":
                raise
            target = (
                Path(execution.output_root)
                / "runs"
                / definition.job_id
                / "documents"
                / definition.request.output_relative_path
            )
            expected_digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
            if (
                not target.is_file()
                or hashlib.sha256(target.read_bytes()).hexdigest() != expected_digest
            ):
                raise revision_error(
                    "FINAL_QUALITY_GATE_FAILED", {"job_id": definition.job_id}
                ) from error
            run_root = Path(execution.output_root) / "runs" / definition.job_id
            report = run_root / "_reports/synthesis.json"
            if not report.is_file():
                raise revision_error(
                    "FINAL_QUALITY_GATE_FAILED", {"job_id": definition.job_id}
                ) from error
            try:
                synthesis = json.loads(report.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as parse_error:
                raise revision_error(
                    "FINAL_QUALITY_GATE_FAILED", {"job_id": definition.job_id}
                ) from parse_error
            if (
                not isinstance(synthesis, dict)
                or synthesis.get("schema_version") != 1
                or synthesis.get("run_id") != definition.job_id
                or synthesis.get("output_relative_path")
                != definition.request.output_relative_path
                or synthesis.get("output_sha256") != expected_digest
                or synthesis.get("model_id") != execution.model_id
                or synthesis.get("model_revision") != execution.model_revision
            ):
                raise revision_error(
                    "FINAL_QUALITY_GATE_FAILED", {"job_id": definition.job_id}
                ) from error

    def _source(
        self, definition: StoredDocumentJobDefinitionDto
    ) -> TextDocumentCollectionPort:
        return self._source_factory(Path(definition.request.source_root))

    async def _read_documents(
        self, source: TextDocumentCollectionPort
    ) -> tuple[TextDocumentDto, ...]:
        paths = await source.list_relative_paths()
        if not paths:
            raise revision_error("NO_TEXT_DOCUMENTS")
        documents = [await source.read(path) for path in paths]
        return tuple(documents)

    async def _source_manifest(
        self,
        job_id: str,
        definition: StoredDocumentJobDefinitionDto,
    ) -> tuple[dict[str, object], ...]:
        value = await self._artifacts.read_json(job_id, "source-manifest.json")
        try:
            if (
                value.get("schema_version") != 1
                or value.get("job_id") != job_id
                or value.get("pipeline_fingerprint")
                != definition.request.pipeline_fingerprint
                or value.get("source_root") != definition.request.source_root
            ):
                raise ValueError("source manifest mismatch")
            files = value["files"]
            if not isinstance(files, list):
                raise ValueError("source manifest files missing")
            records = tuple(self._manifest_record(item) for item in files)
            if not records or len(records) != len({item["relative_path"] for item in records}):
                raise ValueError("source manifest paths are invalid")
            return records
        except (KeyError, TypeError, ValueError) as error:
            raise revision_error("INPUT_HASH_CHANGED", {"job_id": job_id}) from error

    @staticmethod
    def _document_record(document: TextDocumentDto) -> dict[str, object]:
        return {
            "relative_path": document.relative_path,
            "source_sha256": document.source_sha256,
            "byte_count": len(document.text.encode("utf-8")),
        }

    @classmethod
    def _manifest_record(cls, value: Any) -> dict[str, object]:
        if not isinstance(value, dict):
            raise ValueError("manifest record must be an object")
        relative_path = value.get("relative_path")
        source_sha256 = value.get("source_sha256")
        byte_count = value.get("byte_count")
        if (
            not isinstance(relative_path, str)
            or not isinstance(source_sha256, str)
            or not _SHA256.fullmatch(source_sha256)
            or isinstance(byte_count, bool)
            or not isinstance(byte_count, int)
            or byte_count < 0
        ):
            raise ValueError("manifest record is invalid")
        return {
            "relative_path": relative_path,
            "source_sha256": source_sha256,
            "byte_count": byte_count,
        }

    async def _write_or_verify_json(
        self,
        job_id: str,
        path: str,
        value: dict[str, object],
    ) -> None:
        try:
            await self._artifacts.write_json_once(job_id, path, value)
        except ApplicationError as error:
            if error.code != "JOB_ARTIFACT_ALREADY_EXISTS":
                raise
            if await self._artifacts.read_json(job_id, path) != value:
                raise revision_error("INPUT_HASH_CHANGED", {"job_id": job_id}) from error

    @staticmethod
    async def _load_optional(operation: Callable[..., Awaitable[Any]], *args: str) -> Any | None:
        try:
            return await operation(*args)
        except ApplicationError as error:
            if error.code == "JOB_ARTIFACT_NOT_FOUND":
                return None
            raise

    @staticmethod
    def _title(definition: StoredDocumentJobDefinitionDto) -> str:
        return Path(definition.request.output_relative_path).stem.replace("-", " ").strip()

    @staticmethod
    def _integer(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise revision_error("FINAL_QUALITY_GATE_FAILED")
        return value
