from __future__ import annotations

import threading

from enterprise_rag.domain.errors import revision_error


class ThreadCancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> bool:
        with self._lock:
            if self._event.is_set():
                return False
            self._event.set()
            return True

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise revision_error("JOB_CANCELLED")
