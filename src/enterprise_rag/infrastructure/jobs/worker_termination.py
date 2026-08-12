from __future__ import annotations

import os
import signal
import threading

from enterprise_rag.application.ports.cancellation import (
    CancellationControllerPort,
)


class WorkerTerminationGuard:
    """Turns SIGTERM into cooperative cancellation with a hard-stop deadline."""

    def __init__(
        self,
        cancellation: CancellationControllerPort,
        grace_seconds: int,
    ) -> None:
        if grace_seconds < 1:
            raise ValueError("cancellation grace must be positive")
        self._cancellation = cancellation
        self._grace_seconds = grace_seconds
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def request(self) -> None:
        with self._lock:
            if not self._cancellation.cancel():
                return
            timer = threading.Timer(self._grace_seconds, self._force_exit)
            timer.daemon = True
            self._timer = timer
            timer.start()

    def close(self) -> None:
        with self._lock:
            timer = self._timer
            self._timer = None
        if timer is not None:
            timer.cancel()

    @staticmethod
    def _force_exit() -> None:
        process_id = os.getpid()
        try:
            if os.getpgrp() == process_id:
                os.killpg(process_id, signal.SIGKILL)
            else:
                os.kill(process_id, signal.SIGKILL)
        except ProcessLookupError:
            return
