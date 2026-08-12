from __future__ import annotations

from dataclasses import dataclass

from enterprise_rag.application.ports.cancellation import WorkerTerminationPort
from enterprise_rag.application.ports.clock import ClockPort
from enterprise_rag.application.ports.runner_lease_repository import (
    RunnerLeaseRepositoryPort,
)
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


@dataclass(frozen=True, slots=True)
class RuntimeDiagnosticsDto:
    schema_version: int
    environment: str
    web_enabled: bool
    operating_context_tokens: int
    chunk_max_tokens: int
    token_counter: str
    model_id: str
    model_revision: str
    mlx_lm_available: bool
    before_root_readable: bool
    after_root_available: bool


@dataclass(frozen=True, slots=True)
class DesktopRuntimeDto:
    checkpoint_root: str
    cancellation_grace_seconds: int


@dataclass(frozen=True, slots=True)
class Application:
    diagnostics: RuntimeDiagnosticsDto
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
    runtime: DesktopRuntimeDto
    create_document_job: CreateDocumentJob
    create_configured_document_job: CreateConfiguredDocumentJob
    get_document_job: GetDocumentJob
    list_document_jobs: ListDocumentJobs
    list_document_job_events: ListDocumentJobEvents
    request_document_job_cancellation: RequestDocumentJobCancellation
    get_desktop_settings: GetDesktopSettings
    update_desktop_settings: UpdateDesktopSettings
    browse_local_models: BrowseLocalModels
    search_huggingface_models: SearchHuggingFaceModels
    inspect_model_selection: InspectModelSelection
    download_model: DownloadModel
    cancel_model_download: CancelModelDownload
    get_job_dashboard: GetJobDashboard
    get_document_job_result: GetDocumentJobResult
    get_completion_notification_status: GetCompletionNotificationStatus
    notify_document_job_completion: NotifyDocumentJobCompletion
    start_document_job: StartDocumentJob

    def close(self) -> None:
        return None

    def __enter__(self) -> JobApplication:
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        self.close()


@dataclass(frozen=True, slots=True)
class JobWorkerApplication:
    run_document_job: RunDocumentJob
    runner_leases: RunnerLeaseRepositoryPort
    clock: ClockPort
    heartbeat_seconds: int
    termination: WorkerTerminationPort
    confirm_document_job_cancellation: ConfirmDocumentJobCancellation
    notify_document_job_completion: NotifyDocumentJobCompletion

    def close(self) -> None:
        self.termination.close()

    def __enter__(self) -> JobWorkerApplication:
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        self.close()
