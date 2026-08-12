from __future__ import annotations

from typing import Protocol


class CancellationTokenPort(Protocol):
    @property
    def is_cancelled(self) -> bool:
        raise NotImplementedError

    def raise_if_cancelled(self) -> None:
        raise NotImplementedError


class CancellationControllerPort(CancellationTokenPort, Protocol):
    def cancel(self) -> bool:
        """Request cancellation, returning whether this was the first request."""
        raise NotImplementedError


class RunnerCancellationPort(Protocol):
    async def request(self, job_id: str) -> bool:
        """Signal the active runner, returning whether a signal was delivered."""
        raise NotImplementedError


class WorkerTerminationPort(Protocol):
    def request(self) -> None:
        """Begin cooperative cancellation and arm the hard-stop deadline."""
        raise NotImplementedError

    def close(self) -> None:
        """Disarm any pending hard-stop deadline."""
        raise NotImplementedError
