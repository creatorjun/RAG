from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from enterprise_rag.bootstrap import (
    build_job_application,
    build_job_worker_application,
)


class JobBootstrapTest(unittest.TestCase):
    def test_builds_control_and_worker_composition_without_loading_model(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary).resolve()
            shutil.copytree(repository_root / "config", project_root / "config")
            (project_root / "data/before").mkdir(parents=True)
            (project_root / "data/after").mkdir(parents=True)

            with build_job_application(project_root, "development") as control:
                settings = control.get_desktop_settings.execute
                self.assertTrue(callable(settings))
                self.assertTrue(callable(control.start_document_job.execute))
                self.assertTrue(callable(control.browse_local_models.execute))
                self.assertTrue(callable(control.inspect_model_selection.execute))
                self.assertTrue(callable(control.download_model.execute))
                self.assertTrue(callable(control.cancel_model_download.execute))
                self.assertTrue(callable(control.get_document_job_result.execute))
                self.assertTrue(
                    callable(control.get_completion_notification_status.execute)
                )
                self.assertTrue(callable(control.notify_document_job_completion.execute))
            with build_job_worker_application(project_root, "development") as worker:
                self.assertTrue(callable(worker.run_document_job.execute))
                self.assertTrue(callable(worker.runner_leases.heartbeat))
                self.assertEqual(worker.heartbeat_seconds, 5)
                self.assertTrue(callable(worker.termination.request))
                self.assertTrue(callable(worker.termination.close))
                self.assertTrue(callable(worker.notify_document_job_completion.execute))


if __name__ == "__main__":
    unittest.main()
