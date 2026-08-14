from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path

from enterprise_rag.infrastructure.config.settings import LoggingSettings
from enterprise_rag.infrastructure.logging import configure_logging, shutdown_logging


class LoggingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.log_root = Path(self._temporary.name)
        self.logger = logging.getLogger("enterprise_rag.tests.logging")

    def tearDown(self) -> None:
        shutdown_logging()
        self._temporary.cleanup()

    def test_writes_structured_context_and_exception_stack(self) -> None:
        log_path = configure_logging(
            self.log_root,
            self._settings(),
            "test-component",
        )
        self.logger.info(
            "job_started",
            extra={
                "job_id": "job-123",
                "context_tokens": 16_384,
                "runner_token": "must-not-appear",
                "details": {"source_text": "private", "count": 3},
            },
        )
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            self.logger.exception("job_crashed", extra={"job_id": "job-123"})

        records = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
        ]
        started = records[-2]
        crashed = records[-1]
        self.assertEqual(started["component"], "test-component")
        self.assertEqual(started["job_id"], "job-123")
        self.assertEqual(started["context_tokens"], 16_384)
        self.assertEqual(started["runner_token"], "[REDACTED]")
        self.assertEqual(started["details"]["source_text"], "[REDACTED]")
        self.assertNotIn("must-not-appear", log_path.read_text(encoding="utf-8"))
        self.assertEqual(crashed["exception"]["type"], "RuntimeError")
        self.assertIn("RuntimeError: boom", crashed["exception"]["stack_trace"])
        self.assertTrue(crashed["timestamp"].endswith("Z"))

    def test_rotates_at_the_configured_size_and_retains_bounded_backups(self) -> None:
        log_path = configure_logging(
            self.log_root,
            self._settings(maximum_file_bytes=1024, retained_files=2),
            "rotation-test",
        )
        for sequence in range(30):
            self.logger.info(
                "large_record",
                extra={"sequence": sequence, "detail": "x" * 200},
            )

        self.assertTrue(log_path.is_file())
        self.assertTrue(Path(f"{log_path}.1").is_file())
        self.assertTrue(Path(f"{log_path}.2").is_file())
        self.assertFalse(Path(f"{log_path}.3").exists())
        for path in (log_path, Path(f"{log_path}.1"), Path(f"{log_path}.2")):
            for line in path.read_text(encoding="utf-8").splitlines():
                self.assertIsInstance(json.loads(line), dict)

    @staticmethod
    def _settings(
        maximum_file_bytes: int = 100 * 1024 * 1024,
        retained_files: int = 30,
    ) -> LoggingSettings:
        return LoggingSettings(
            level="DEBUG",
            maximum_file_bytes=maximum_file_bytes,
            retained_files=retained_files,
        )


if __name__ == "__main__":
    unittest.main()
