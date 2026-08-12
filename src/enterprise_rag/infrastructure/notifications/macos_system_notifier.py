from __future__ import annotations

import asyncio
import platform
import subprocess
from pathlib import Path

from enterprise_rag.domain.errors import revision_error

_SCRIPT = (
    'display notification (system attribute "RAG_NOTIFICATION_BODY") '
    'with title (system attribute "RAG_NOTIFICATION_TITLE")'
)


class MacOsSystemNotifier:
    def __init__(self, executable: Path = Path("/usr/bin/osascript")) -> None:
        self._executable = executable

    async def send(self, title: str, message: str) -> None:
        if not title.strip() or not message.strip():
            raise ValueError("notification title and message are required")
        if platform.system() != "Darwin" or not self._executable.is_file():
            raise revision_error("NOTIFICATION_UNAVAILABLE")
        await asyncio.to_thread(self._send, title[:128], message[:512])

    def _send(self, title: str, message: str) -> None:
        try:
            completed = subprocess.run(
                (str(self._executable), "-e", _SCRIPT),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
                env={
                    "PATH": "/usr/bin:/bin",
                    "RAG_NOTIFICATION_TITLE": title,
                    "RAG_NOTIFICATION_BODY": message,
                },
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise revision_error("NOTIFICATION_FAILED") from error
        if completed.returncode != 0:
            raise revision_error("NOTIFICATION_FAILED")
