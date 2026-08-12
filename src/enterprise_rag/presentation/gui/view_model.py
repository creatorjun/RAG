from __future__ import annotations

import asyncio
from uuid import uuid4

from enterprise_rag.application.dto.desktop_settings import DesktopSettingsDto
from enterprise_rag.application.dto.job_dashboard import JobDashboardDto
from enterprise_rag.application.dto.jobs import DocumentJobDto
from enterprise_rag.application.dto.model_catalog import (
    ModelCatalogDto,
    ModelCatalogEntryDto,
)
from enterprise_rag.application.ports.model_download import (
    ModelDownloadProgressCallback,
)
from enterprise_rag.bootstrap import JobApplication


class DesktopViewModel:
    def __init__(self, application: JobApplication) -> None:
        self._application = application

    @property
    def checkpoint_root(self) -> str:
        return str(self._application.configuration.paths.var_root / "jobs")

    def load_settings(self) -> DesktopSettingsDto:
        return asyncio.run(self._application.get_desktop_settings.execute())

    def save_settings(self, desired: DesktopSettingsDto) -> DesktopSettingsDto:
        return asyncio.run(
            self._application.update_desktop_settings.execute(
                desired.settings_revision,
                desired,
            )
        )

    def list_jobs(self, limit: int = 100) -> tuple[DocumentJobDto, ...]:
        return asyncio.run(self._application.list_document_jobs.execute(limit))

    def local_models(self, query: str = "") -> ModelCatalogDto:
        return asyncio.run(self._application.browse_local_models.execute(query))

    def search_models(self, query: str) -> ModelCatalogDto:
        return asyncio.run(self._application.search_huggingface_models.execute(query))

    def inspect_model(
        self,
        model_id: str,
        revision: str,
        offline_mode: bool,
    ) -> ModelCatalogEntryDto:
        return asyncio.run(
            self._application.inspect_model_selection.execute(
                model_id,
                revision,
                offline_mode,
            )
        )

    @staticmethod
    def new_model_download_id() -> str:
        return f"download-{uuid4().hex}"

    def download_model(
        self,
        download_id: str,
        model_id: str,
        revision: str,
        progress: ModelDownloadProgressCallback,
    ) -> ModelCatalogEntryDto:
        return asyncio.run(
            self._application.download_model.execute(
                download_id,
                model_id,
                revision,
                progress,
            )
        )

    def cancel_model_download(self, download_id: str) -> bool:
        return asyncio.run(
            self._application.cancel_model_download.execute(download_id)
        )

    def create_job(
        self,
        instruction: str,
        output_relative_path: str,
    ) -> DocumentJobDto:
        return asyncio.run(
            self._application.create_configured_document_job.execute(
                instruction,
                output_relative_path,
            )
        )

    def dashboard(self, job_id: str) -> JobDashboardDto:
        return asyncio.run(self._application.get_job_dashboard.execute(job_id))

    def start_job(self, job_id: str) -> int:
        launched = asyncio.run(self._application.start_document_job.execute(job_id))
        return launched.process_id

    def cancel_job(self, job_id: str) -> DocumentJobDto:
        return asyncio.run(
            self._application.request_document_job_cancellation.execute(job_id)
        )

    def close(self) -> None:
        self._application.close()
