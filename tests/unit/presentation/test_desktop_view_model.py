from __future__ import annotations

import unittest

from enterprise_rag.application.dto.desktop_settings import DesktopSettingsDto
from enterprise_rag.application.dto.job_dashboard import JobDashboardDto
from enterprise_rag.application.dto.job_result import (
    CompletionNotificationDto,
    CompletionNotificationState,
    DocumentJobResultDto,
    JobResultAvailability,
)
from enterprise_rag.application.dto.jobs import DocumentJobDto
from enterprise_rag.application.dto.model_catalog import (
    ModelCatalogDto,
    ModelCatalogEntryDto,
    ModelCatalogOrigin,
    ModelCompatibility,
)
from enterprise_rag.application.runtime import DesktopRuntimeDto
from enterprise_rag.domain.jobs import DocumentJobState
from enterprise_rag.presentation.gui.view_model import DesktopViewModel


class _AsyncCall:
    def __init__(self, result) -> None:
        self.result = result
        self.arguments = None

    async def execute(self, *arguments):
        self.arguments = arguments
        return self.result


class _Application:
    def __init__(self, settings: DesktopSettingsDto) -> None:
        job = DocumentJobDto("job-" + "a" * 32, DocumentJobState.CREATED, 0, 0)
        dashboard = JobDashboardDto(job, (), ())
        self.runtime = DesktopRuntimeDto(
            "/workspace/var/jobs",
            15,
        )
        self.get_desktop_settings = _AsyncCall(settings)
        self.update_desktop_settings = _AsyncCall(settings)
        self.list_document_jobs = _AsyncCall((job,))
        self.create_configured_document_job = _AsyncCall(job)
        self.get_job_dashboard = _AsyncCall(dashboard)
        result = DocumentJobResultDto(
            job.job_id,
            job.state,
            JobResultAvailability.NOT_READY,
            True,
        )
        notification = CompletionNotificationDto(
            job.job_id,
            CompletionNotificationState.NOT_READY,
        )
        self.get_document_job_result = _AsyncCall(result)
        self.get_completion_notification_status = _AsyncCall(notification)
        self.notify_document_job_completion = _AsyncCall(notification)
        self.start_document_job = _AsyncCall(
            type("Launch", (), {"process_id": 321})()
        )
        self.request_document_job_cancellation = _AsyncCall(job)
        entry = ModelCatalogEntryDto(
            "mlx-community/Test-4bit",
            "a" * 40,
            ModelCatalogOrigin.LOCAL_CACHE,
            True,
            1,
            "4-bit",
            16_384,
            "apache-2.0",
            None,
            ModelCompatibility.SUPPORTED,
            "적합",
            "/cache/test",
        )
        self.browse_local_models = _AsyncCall(ModelCatalogDto("", False, (entry,)))
        self.search_huggingface_models = _AsyncCall(ModelCatalogDto("test", True, (entry,)))
        self.inspect_model_selection = _AsyncCall(entry)
        self.download_model = _AsyncCall(entry)
        self.cancel_model_download = _AsyncCall(True)
        self.closed = False

    def close(self) -> None:
        self.closed = True


class DesktopViewModelTest(unittest.TestCase):
    def test_delegates_all_gui_actions_to_application_use_cases(self) -> None:
        settings = DesktopSettingsDto(
            0,
            "/workspace/source",
            "/workspace/output",
            "mlx-community/Qwen3.6-27B-4bit",
            "a" * 40,
            16_384,
            4_096,
            "",
            3,
            True,
            True,
        )
        application = _Application(settings)
        view_model = DesktopViewModel(application)  # type: ignore[arg-type]
        self.assertEqual(view_model.checkpoint_root, "/workspace/var/jobs")
        self.assertEqual(view_model.cancellation_grace_seconds, 15)
        self.assertEqual(view_model.load_settings(), settings)
        self.assertEqual(view_model.save_settings(settings), settings)
        self.assertEqual(view_model.list_jobs()[0].job_id, "job-" + "a" * 32)
        self.assertFalse(view_model.local_models().remote)
        self.assertTrue(view_model.search_models("test").remote)
        self.assertTrue(
            view_model.inspect_model(
                "mlx-community/Test-4bit", "a" * 40, True
            ).cached
        )
        download_id = view_model.new_model_download_id()
        self.assertTrue(download_id.startswith("download-"))
        self.assertTrue(
            view_model.download_model(
                download_id,
                "mlx-community/Test-4bit",
                "a" * 40,
                lambda _: None,
            ).cached
        )
        self.assertTrue(view_model.cancel_model_download(download_id))
        self.assertEqual(
            view_model.create_job("문서 작성", "guide.md").state,
            DocumentJobState.CREATED,
        )
        self.assertEqual(
            view_model.dashboard("job-" + "a" * 32).job.state,
            DocumentJobState.CREATED,
        )
        self.assertEqual(
            view_model.job_result("job-" + "a" * 32),
            application.get_document_job_result.result,
        )
        self.assertEqual(
            view_model.completion_notification_status("job-" + "a" * 32),
            application.get_completion_notification_status.result,
        )
        self.assertEqual(
            view_model.notify_completion("job-" + "a" * 32),
            application.notify_document_job_completion.result,
        )
        self.assertEqual(view_model.start_job("job-" + "a" * 32), 321)
        self.assertEqual(
            view_model.cancel_job("job-" + "a" * 32).state,
            DocumentJobState.CREATED,
        )
        view_model.close()
        self.assertTrue(application.closed)


if __name__ == "__main__":
    unittest.main()
