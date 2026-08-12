from __future__ import annotations

from collections.abc import Callable

from enterprise_rag.application.dto.progress import ProgressEventDto

ProgressCallback = Callable[[ProgressEventDto], None]


class ProgressReporter:
    def __init__(
        self,
        callback: ProgressCallback | None = None,
        job_id: str | None = None,
    ) -> None:
        self._callback = callback
        self._job_id = job_id
        self._sequence = 0
        self._last_percentage = 0

    def emit(
        self,
        percentage: int | None,
        stage: str,
        message: str,
        completed: int | None = None,
        total: int | None = None,
        counter_name: str | None = None,
    ) -> ProgressEventDto:
        if percentage is not None:
            if percentage < self._last_percentage:
                raise ValueError("progress percentage cannot decrease")
            self._last_percentage = percentage
        self._sequence += 1
        event = ProgressEventDto(
            percentage=percentage,
            stage=stage,
            message=message,
            completed=completed,
            total=total,
            counter_name=counter_name,
            job_id=self._job_id,
            sequence=self._sequence,
        )
        if self._callback is not None:
            self._callback(event)
        return event
