# src/enterprise_rag/bootstrap.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from enterprise_rag.application.dto.long_document import ChunkingConfigDto
from enterprise_rag.application.use_cases.build_evidence_bundle import BuildEvidenceBundle
from enterprise_rag.application.use_cases.compare_revision_run import CompareRevisionRun
from enterprise_rag.application.use_cases.create_document_job import CreateDocumentJob
from enterprise_rag.application.use_cases.finalize_revision_run import FinalizeRevisionRun
from enterprise_rag.application.use_cases.inspect_integration_sources import (
    InspectIntegrationSources,
)
from enterprise_rag.application.use_cases.integrate_documents import IntegrateDocuments
from enterprise_rag.application.use_cases.manage_document_jobs import (
    GetDocumentJob,
    ListDocumentJobEvents,
    ListDocumentJobs,
    RequestDocumentJobCancellation,
)
from enterprise_rag.application.use_cases.plan_long_document import PlanLongDocument
from enterprise_rag.application.use_cases.prepare_revision_run import PrepareRevisionRun
from enterprise_rag.domain.context_budget import TokenBudget
from enterprise_rag.infrastructure.chunking.structure_aware_text_chunker import (
    StructureAwareTextChunker,
)
from enterprise_rag.infrastructure.clock.system import SystemClock, UuidIdGenerator
from enterprise_rag.infrastructure.config.settings import LoadedSettings, SettingsLoader
from enterprise_rag.infrastructure.jobs.filesystem_job_artifact_repository import (
    FilesystemJobArtifactRepository,
)
from enterprise_rag.infrastructure.models.mlx_text_generator import MlxTextGenerator
from enterprise_rag.infrastructure.persistence.sqlite_document_job_repository import (
    SqliteDocumentJobRepository,
)
from enterprise_rag.infrastructure.planning.hierarchical_context_planner import (
    HierarchicalContextPlanner,
)
from enterprise_rag.infrastructure.sources.before_text_source import BeforeTextDocumentSource
from enterprise_rag.infrastructure.tokenization.conservative_utf8 import (
    ConservativeUtf8TokenCounter,
)
from enterprise_rag.infrastructure.workspace.folder_revision_workspace import (
    FolderRevisionWorkspace,
)
from enterprise_rag.infrastructure.workspace.folder_tree_comparator import FolderTreeComparator


@dataclass(frozen=True, slots=True)
class Application:
    configuration: LoadedSettings
    prepare_revision_run: PrepareRevisionRun
    compare_revision_run: CompareRevisionRun
    finalize_revision_run: FinalizeRevisionRun
    plan_long_document: PlanLongDocument
    integrate_documents: IntegrateDocuments

    def close(self) -> None:
        return None

    def __enter__(self) -> Application:
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        self.close()


@dataclass(frozen=True, slots=True)
class JobApplication:
    configuration: LoadedSettings
    create_document_job: CreateDocumentJob
    get_document_job: GetDocumentJob
    list_document_jobs: ListDocumentJobs
    list_document_job_events: ListDocumentJobEvents
    request_document_job_cancellation: RequestDocumentJobCancellation

    def close(self) -> None:
        return None

    def __enter__(self) -> JobApplication:
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        self.close()


def build_application(project_root: Path, environment: str | None = None) -> Application:
    configuration = SettingsLoader(project_root).load(environment)
    settings = configuration.settings
    clock = SystemClock()
    id_generator = UuidIdGenerator()
    workspace = FolderRevisionWorkspace(
        before_root=configuration.paths.before_root,
        after_root=configuration.paths.after_root,
        comparator=FolderTreeComparator(),
        clock=clock,
        id_generator=id_generator,
        max_file_bytes=settings.sources.max_file_bytes,
    )
    token_counter = ConservativeUtf8TokenCounter()
    source = BeforeTextDocumentSource(
        configuration.paths.before_root,
        settings.sources.text_max_file_bytes,
    )
    chunker = StructureAwareTextChunker(token_counter)
    planner = HierarchicalContextPlanner()
    chunking_config = ChunkingConfigDto(
        tokenizer_id=settings.chunking.tokenizer_id,
        chunker_version=settings.chunking.version,
        target_tokens=settings.chunking.target_tokens,
        max_tokens=settings.chunking.max_tokens,
        minimum_tokens=settings.chunking.minimum_tokens,
        overlap_ratio=settings.chunking.overlap_ratio,
    )
    map_budget = TokenBudget(
        settings.models.llm.context_tokens,
        settings.synthesis.map_prompt_overhead_tokens,
        settings.synthesis.map_max_output_tokens,
        settings.models.llm.reserved_tokens,
        settings.synthesis.input_budget_ratio,
    )
    reduce_budget = TokenBudget(
        settings.models.llm.context_tokens,
        settings.synthesis.reduce_prompt_overhead_tokens,
        settings.synthesis.reduce_max_output_tokens,
        settings.models.llm.reserved_tokens,
        settings.synthesis.input_budget_ratio,
    )
    plan_long_document = PlanLongDocument(
        source=source,
        chunker=chunker,
        planner=planner,
        chunking_config=chunking_config,
        map_budget=map_budget,
        reduce_budget=reduce_budget,
        item_overhead_tokens=settings.synthesis.batch_item_overhead_tokens,
        separator_tokens=settings.synthesis.batch_separator_tokens,
    )
    integrate_documents = IntegrateDocuments(
        source_inspector=InspectIntegrationSources(source, chunker, chunking_config),
        evidence_builder=BuildEvidenceBundle(),
        workspace=workspace,
        planner=planner,
        generator=MlxTextGenerator(
            model_id=settings.models.llm.model_id,
            model_revision=settings.models.llm.revision,
            maximum_context_tokens=settings.models.llm.context_tokens,
            reserved_tokens=settings.models.llm.reserved_tokens,
        ),
        clock=clock,
        id_generator=id_generator,
        map_budget=map_budget,
        reduce_budget=reduce_budget,
        final_max_output_tokens=settings.synthesis.final_max_output_tokens,
        item_overhead_tokens=settings.synthesis.batch_item_overhead_tokens,
        separator_tokens=settings.synthesis.batch_separator_tokens,
    )
    return Application(
        configuration=configuration,
        prepare_revision_run=PrepareRevisionRun(workspace),
        compare_revision_run=CompareRevisionRun(workspace),
        finalize_revision_run=FinalizeRevisionRun(workspace),
        plan_long_document=plan_long_document,
        integrate_documents=integrate_documents,
    )


def build_job_application(
    project_root: Path,
    environment: str | None = None,
) -> JobApplication:
    configuration = SettingsLoader(project_root).load(environment)
    clock = SystemClock()
    repository = SqliteDocumentJobRepository(configuration.paths.database, clock)
    artifacts = FilesystemJobArtifactRepository(configuration.paths.var_root)
    return JobApplication(
        configuration=configuration,
        create_document_job=CreateDocumentJob(repository, artifacts, UuidIdGenerator()),
        get_document_job=GetDocumentJob(repository),
        list_document_jobs=ListDocumentJobs(repository),
        list_document_job_events=ListDocumentJobEvents(repository),
        request_document_job_cancellation=RequestDocumentJobCancellation(repository),
    )
