from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from enterprise_rag.application.dto.model_stream import (
    ModelStreamEventDto,
    ModelStreamEventKind,
)
from enterprise_rag.application.ports.clock import ClockPort, IdGeneratorPort
from enterprise_rag.application.ports.model_stream import ModelStreamRepositoryPort
from enterprise_rag.application.ports.text_generator import TextGeneratorPort
from enterprise_rag.domain.errors import ApplicationError

_DELTA_FLUSH_CHARS = 128
DeltaObserver = Callable[[str], None]


class ObservedTextGenerator:
    def __init__(
        self,
        delegate: TextGeneratorPort,
        job_id: str,
        stage: str,
        streams: ModelStreamRepositoryPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._delegate = delegate
        self._job_id = job_id
        self._stage = stage
        self._streams = streams
        self._clock = clock
        self._ids = ids

    @property
    def model_id(self) -> str:
        return self._delegate.model_id

    @property
    def model_revision(self) -> str:
        return self._delegate.model_revision

    async def prepare(self) -> None:
        await self._delegate.prepare()

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        generation_id = "generation-" + self._ids.new_id().lower()
        self._append(generation_id, ModelStreamEventKind.STARTED)
        buffered: list[str] = []
        buffered_chars = 0

        def observe(piece: str) -> None:
            nonlocal buffered_chars
            if not piece:
                return
            buffered.append(piece)
            buffered_chars += len(piece)
            if buffered_chars >= _DELTA_FLUSH_CHARS or "\n" in piece:
                self._flush(generation_id, buffered)
                buffered_chars = 0

        try:
            generate_stream = getattr(self._delegate, "generate_stream", None)
            if callable(generate_stream):
                result = await cast(Callable[..., Any], generate_stream)(
                    system_prompt,
                    user_prompt,
                    max_output_tokens,
                    observe,
                )
            else:
                result = await self._delegate.generate(
                    system_prompt,
                    user_prompt,
                    max_output_tokens,
                )
                observe(result)
            self._flush(generation_id, buffered)
            self._append(generation_id, ModelStreamEventKind.COMPLETED)
            return str(result)
        except Exception as error:
            self._flush(generation_id, buffered)
            code = error.code if isinstance(error, ApplicationError) else "MODEL_GENERATION_FAILED"
            self._append(
                generation_id,
                ModelStreamEventKind.FAILED,
                error_code=code,
            )
            raise

    def _flush(self, generation_id: str, buffered: list[str]) -> None:
        if not buffered:
            return
        text = "".join(buffered)
        buffered.clear()
        for start in range(0, len(text), 4_096):
            self._append(
                generation_id,
                ModelStreamEventKind.DELTA,
                text=text[start : start + 4_096],
            )

    def _append(
        self,
        generation_id: str,
        kind: ModelStreamEventKind,
        text: str = "",
        error_code: str | None = None,
    ) -> None:
        try:
            self._streams.append(
                ModelStreamEventDto(
                    job_id=self._job_id,
                    sequence=self._streams.next_sequence(self._job_id),
                    generation_id=generation_id,
                    stage=self._stage,
                    kind=kind,
                    text=text,
                    occurred_at=self._clock.now(),
                    error_code=error_code,
                )
            )
        except (ApplicationError, ValueError):
            # Observability must not invalidate an otherwise valid model result.
            return
