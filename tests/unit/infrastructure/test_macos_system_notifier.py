from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.infrastructure.notifications.macos_system_notifier import (
    MacOsSystemNotifier,
)


class MacOsSystemNotifierTest(unittest.TestCase):
    def test_uses_static_applescript_and_environment_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "osascript"
            executable.touch()
            notifier = MacOsSystemNotifier(executable)
            completed = subprocess.CompletedProcess((), 0)
            with (
                patch("platform.system", return_value="Darwin"),
                patch("subprocess.run", return_value=completed) as run,
            ):
                asyncio.run(notifier.send('완료 "title"', "job; do shell script"))
        arguments, options = run.call_args
        self.assertEqual(arguments[0][0], str(executable))
        self.assertNotIn("job; do shell script", arguments[0][2])
        self.assertEqual(options["env"]["RAG_NOTIFICATION_TITLE"], '완료 "title"')
        self.assertEqual(options["env"]["RAG_NOTIFICATION_BODY"], "job; do shell script")
        self.assertEqual(options["timeout"], 5)

    def test_reports_unsupported_platform_and_delivery_failure(self) -> None:
        with patch("platform.system", return_value="Linux"):
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(MacOsSystemNotifier().send("title", "message"))
        self.assertEqual(captured.exception.code, "NOTIFICATION_UNAVAILABLE")

        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "osascript"
            executable.touch()
            notifier = MacOsSystemNotifier(executable)
            with (
                patch("platform.system", return_value="Darwin"),
                patch(
                    "subprocess.run",
                    return_value=subprocess.CompletedProcess((), 1),
                ),
                self.assertRaises(ApplicationError) as captured,
            ):
                asyncio.run(notifier.send("title", "message"))
        self.assertEqual(captured.exception.code, "NOTIFICATION_FAILED")


if __name__ == "__main__":
    unittest.main()
