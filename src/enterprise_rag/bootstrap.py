# src/enterprise_rag/bootstrap.py
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

from enterprise_rag.application.dto.desktop_settings import DesktopSettingsDto
from enterprise_rag.application.dto.jobs import StoredDocumentJobDefinitionDto
from enterprise_rag.application.dto.long_document import ChunkingConfigDto
from enterprise_rag.application.ports.text_generator import TextGeneratorPort
from enterprise_rag.application.runtime import (
    Application,
    DesktopRuntimeDto,
    JobApplication,
    JobWorkerApplication,
    RuntimeDiagnosticsDto,
)
from enterprise_rag.application.use_cases.build_evidence_bundle import BuildEvidenceBundle
from enterprise_rag.application.use_cases.compare_revision_run import CompareRevisionRun
from enterprise_rag.application.use_cases.create_configured_document_job import (
    CreateConfiguredDocumentJob,
)
from enterprise_rag.application.use_cases.create_document_job import CreateDocumentJob
from enterprise_rag.application.use_cases.finalize_revision_run import FinalizeRevisionRun
from enterprise_rag.application.use_cases.get_document_job_result import (
    GetDocumentJobResult,
)
from enterprise_rag.application.use_cases.get_job_dashboard import GetJobDashboard
from enterprise_rag.application.use_cases.inspect_integration_sources import (
    InspectIntegrationSources,
)
from enterprise_rag.application.use_cases.integrate_documents import IntegrateDocuments
from enterprise_rag.application.use_cases.manage_desktop_settings import (
    GetDesktopSettings,
    UpdateDesktopSettings,
)
from enterprise_rag.application.use_cases.manage_document_jobs import (
    ConfirmDocumentJobCancellation,
    GetDocumentJob,
    ListDocumentJobEvents,
    ListDocumentJobs,
    RequestDocumentJobCancellation,
)
from enterprise_rag.application.use_cases.model_catalog import (
    BrowseLocalModels,
    InspectModelSelection,
    SearchHuggingFaceModels,
)
from enterprise_rag.application.use_cases.model_download import (
    CancelModelDownload,
    DownloadModel,
)
from enterprise_rag.application.use_cases.notify_document_job_completion import (
    GetCompletionNotificationStatus,
    NotifyDocumentJobCompletion,
)
from enterprise_rag.application.use_cases.plan_long_document import PlanLongDocument
from enterprise_rag.application.use_cases.prepare_revision_run import PrepareRevisionRun
from enterprise_rag.application.use_cases.run_document_job import RunDocumentJob
from enterprise_rag.application.use_cases.start_document_job import StartDocumentJob
from enterprise_rag.domain.context_budget import TokenBudget
from enterprise_rag.infrastructure.chunking.structure_aware_text_chunker import (
    StructureAwareTextChunker,
)
from enterprise_rag.infrastructure.clock.system import SystemClock, UuidIdGenerator
from enterprise_rag.infrastructure.config.filesystem_desktop_settings_repository import (
    FilesystemDesktopSettingsRepository,
)
from enterprise_rag.infrastructure.config.settings import SettingsLoader
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
from enterprise_rag.infrastructure.jobs.filesystem_runner_lease_repository import (
    FilesystemRunnerLeaseRepository,
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
from enterprise_rag.infrastructure.jobs.posix_runner_cancellation import (
    PosixRunnerCancellation,
)
from enterprise_rag.infrastructure.jobs.subprocess_document_job_launcher import (
    SubprocessDocumentJobLauncher,
)
from enterprise_rag.infrastructure.jobs.thread_cancellation import (
    ThreadCancellationToken,
)
from enterprise_rag.infrastructure.jobs.worker_termination import WorkerTerminationGuard
from enterprise_rag.infrastructure.models.huggingface_model_catalog import (
    HuggingFaceModelCatalog,
)
from enterprise_rag.infrastructure.models.huggingface_model_downloader import (
    HuggingFaceModelDownloader,
)
from enterprise_rag.infrastructure.models.mlx_text_generator import MlxTextGenerator
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
from enterprise_rag.infrastructure.notifications.macos_system_notifier import (
    MacOsSystemNotifier,
)
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
from enterprise_rag.infrastructure.workspace.file_io import sha256_file
from enterprise_rag.infrastructure.workspace.folder_revision_workspace import (
    FolderRevisionWorkspace,
)
from enterprise_rag.infrastructure.workspace.folder_tree_comparator import FolderTreeComparator


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
        diagnostics=RuntimeDiagnosticsDto(
            schema_version=settings.schema_version,
            environment=settings.environment,
            web_enabled=settings.web.enabled,
            operating_context_tokens=settings.models.llm.context_tokens,
            chunk_max_tokens=settings.chunking.max_tokens,
            token_counter=settings.chunking.tokenizer_id,
            model_id=settings.models.llm.model_id,
            model_revision=settings.models.llm.revision,
            mlx_lm_available=importlib.util.find_spec("mlx_lm") is not None,
            before_root_readable=configuration.paths.before_root.is_dir(),
            after_root_available=configuration.paths.after_root.is_dir(),
        ),
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
    settings = configuration.settings
    desktop_repository = FilesystemDesktopSettingsRepository(
        configuration.paths.var_root,
        DesktopSettingsDto(
            settings_revision=0,
            source_root=str(configuration.paths.before_root),
            output_root=str(configuration.paths.after_root),
            model_id=settings.models.llm.model_id,
            model_revision=settings.models.llm.revision,
            context_tokens=settings.models.llm.context_tokens,
            max_output_tokens=settings.synthesis.final_max_output_tokens,
            additional_system_prompt="",
            max_task_attempts=3,
            offline_mode=True,
            notify_on_completion=True,
        ),
    )
    create_job = CreateDocumentJob(repository, artifacts, UuidIdGenerator())
    model_catalog = HuggingFaceModelCatalog()
    inspect_model_selection = InspectModelSelection(model_catalog)
    model_downloader = HuggingFaceModelDownloader(
        model_catalog,
        settings.runtime.model_download_reserve_bytes,
    )
    deployment_fingerprint = hashlib.sha256(
        json.dumps(
            settings.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    evidence = FilesystemEvidenceRepository(artifacts)
    claims = FilesystemClaimLedgerRepository(artifacts)
    claim_drafts = FilesystemClaimDraftRepository(artifacts)
    plans = FilesystemTaskPlanRepository(artifacts)
    results = FilesystemTaskResultRepository(artifacts)
    finals = FilesystemFinalDocumentRepository(artifacts)
    definitions = FilesystemDocumentJobDefinitionRepository(artifacts)
    result_reader = FilesystemDocumentJobResultReader(
        configuration.paths.var_root,
        artifacts,
        definitions,
        finals,
    )
    notification_receipts = FilesystemCompletionNotificationRepository(
        configuration.paths.var_root
    )
    notify_completion = NotifyDocumentJobCompletion(
        repository,
        result_reader,
        notification_receipts,
        MacOsSystemNotifier(),
        clock,
    )
    checkpoint_inspector = FilesystemJobCheckpointInspector(
        artifacts,
        evidence,
        claims,
        plans,
        results,
        finals,
        claim_drafts,
    )
    model_streams = FilesystemModelStreamRepository(configuration.paths.var_root)
    runner_leases = FilesystemRunnerLeaseRepository(configuration.paths.var_root)
    ids = UuidIdGenerator()
    return JobApplication(
        runtime=DesktopRuntimeDto(
            checkpoint_root=str(configuration.paths.var_root / "jobs"),
            cancellation_grace_seconds=settings.runtime.cancellation_grace_seconds,
        ),
        create_document_job=create_job,
        create_configured_document_job=CreateConfiguredDocumentJob(
            desktop_repository,
            create_job,
            deployment_fingerprint,
            inspect_model_selection,
        ),
        get_document_job=GetDocumentJob(repository),
        list_document_jobs=ListDocumentJobs(repository),
        list_document_job_events=ListDocumentJobEvents(repository),
        request_document_job_cancellation=RequestDocumentJobCancellation(
            repository,
            PosixRunnerCancellation(runner_leases),
        ),
        get_desktop_settings=GetDesktopSettings(desktop_repository),
        update_desktop_settings=UpdateDesktopSettings(desktop_repository),
        browse_local_models=BrowseLocalModels(model_catalog),
        search_huggingface_models=SearchHuggingFaceModels(model_catalog),
        inspect_model_selection=inspect_model_selection,
        download_model=DownloadModel(inspect_model_selection, model_downloader),
        cancel_model_download=CancelModelDownload(model_downloader),
        get_job_dashboard=GetJobDashboard(
            repository,
            repository,
            checkpoint_inspector,
            runner_leases,
            clock,
            settings.runtime.worker_start_timeout_seconds,
            settings.runtime.worker_heartbeat_seconds,
            settings.runtime.worker_missed_heartbeats,
            model_streams=model_streams,
        ),
        get_document_job_result=GetDocumentJobResult(repository, result_reader),
        get_completion_notification_status=GetCompletionNotificationStatus(
            repository,
            result_reader,
            notification_receipts,
        ),
        notify_document_job_completion=notify_completion,
        start_document_job=StartDocumentJob(
            repository,
            SubprocessDocumentJobLauncher(
                configuration.paths.project_root,
                configuration.paths.var_root,
                settings.environment,
                runner_leases,
                clock,
                ids,
            ),
        ),
    )


def build_job_worker_application(
    project_root: Path,
    environment: str | None = None,
) -> JobWorkerApplication:
    configuration = SettingsLoader(project_root).load(environment)
    settings = configuration.settings
    clock = SystemClock()
    ids = UuidIdGenerator()
    repository = SqliteDocumentJobRepository(configuration.paths.database, clock)
    artifacts = FilesystemJobArtifactRepository(configuration.paths.var_root)
    evidence = FilesystemEvidenceRepository(artifacts)
    claims = FilesystemClaimLedgerRepository(artifacts)
    claim_drafts = FilesystemClaimDraftRepository(artifacts)
    plans = FilesystemTaskPlanRepository(artifacts)
    results = FilesystemTaskResultRepository(artifacts)
    finals = FilesystemFinalDocumentRepository(artifacts)
    definitions = FilesystemDocumentJobDefinitionRepository(artifacts)
    runner_leases = FilesystemRunnerLeaseRepository(configuration.paths.var_root)
    model_streams = FilesystemModelStreamRepository(configuration.paths.var_root)
    cancellation = ThreadCancellationToken()
    result_reader = FilesystemDocumentJobResultReader(
        configuration.paths.var_root,
        artifacts,
        definitions,
        finals,
    )
    notification_receipts = FilesystemCompletionNotificationRepository(
        configuration.paths.var_root
    )
    notify_completion = NotifyDocumentJobCompletion(
        repository,
        result_reader,
        notification_receipts,
        MacOsSystemNotifier(),
        clock,
    )

    def model_factory(
        definition: StoredDocumentJobDefinitionDto,
    ) -> TextGeneratorPort:
        execution = definition.request.execution_settings
        if execution is None:
            raise ValueError("document job execution settings are required")
        return MlxTextGenerator(
            execution.model_id,
            execution.model_revision,
            execution.context_tokens,
            settings.models.llm.reserved_tokens,
            execution.offline_mode,
            cancellation,
        )

    stages = LocalDocumentJobStages(
        artifacts=artifacts,
        definitions=definitions,
        evidence=evidence,
        claims=claims,
        claim_drafts=claim_drafts,
        plans=plans,
        results=results,
        finals=finals,
        chunking=ChunkingConfigDto(
            tokenizer_id=settings.chunking.tokenizer_id,
            chunker_version=settings.chunking.version,
            target_tokens=settings.chunking.target_tokens,
            max_tokens=settings.chunking.max_tokens,
            minimum_tokens=settings.chunking.minimum_tokens,
            overlap_ratio=settings.chunking.overlap_ratio,
        ),
        chunker=StructureAwareTextChunker(ConservativeUtf8TokenCounter()),
        source_factory=lambda root: BeforeTextDocumentSource(
            root,
            settings.sources.text_max_file_bytes,
        ),
        workspace_factory=lambda before, after: FolderRevisionWorkspace(
            before,
            after,
            FolderTreeComparator(),
            clock,
            ids,
            settings.sources.max_file_bytes,
        ),
        model_factory=model_factory,
        observed_generator_factory=lambda generator, job_id, stage: ObservedTextGenerator(
            generator,
            job_id,
            stage,
            model_streams,
            clock,
            ids,
        ),
        claim_draft_generator_factory=StructuredClaimDraftGenerator,
        claim_relation_generator_factory=StructuredClaimRelationGenerator,
        task_definition_generator_factory=StructuredTaskDefinitionGenerator,
        task_output_generator_factory=StructuredTaskOutputGenerator,
        file_digest=sha256_file,
        cancellation=cancellation,
    ).stages()
    return JobWorkerApplication(
        run_document_job=RunDocumentJob(repository, repository, stages, cancellation),
        runner_leases=runner_leases,
        clock=clock,
        heartbeat_seconds=settings.runtime.worker_heartbeat_seconds,
        termination=WorkerTerminationGuard(
            cancellation,
            settings.runtime.cancellation_grace_seconds,
        ),
        confirm_document_job_cancellation=ConfirmDocumentJobCancellation(repository),
        notify_document_job_completion=notify_completion,
    )


def cli_main(argv: list[str] | None = None) -> int:
    from enterprise_rag.presentation.cli import main

    return main(build_application, build_job_application, argv)


def gui_main(argv: list[str] | None = None) -> int:
    from enterprise_rag.presentation.gui.app import main

    return main(build_job_application, argv)


def job_worker_main(argv: list[str] | None = None) -> int:
    from enterprise_rag.presentation.job_worker import main

    return main(build_job_worker_application, argv)
