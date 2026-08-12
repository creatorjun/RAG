from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone

from enterprise_rag.application.dto.model_stream import ModelStreamEventKind
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.infrastructure.models.observed_text_generator import (
    ObservedTextGenerator,
)


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 12, tzinfo=timezone.utc)


class _Ids:
    def new_id(self) -> str:
        return "1" * 32


class _Streams:
    def __init__(self, fail: bool = False) -> None:
        self.events = []
        self.fail = fail

    def next_sequence(self, job_id: str) -> int:
        return len(self.events) + 1

    def append(self, event) -> None:
        if self.fail:
            raise revision_error("IO_FAILURE")
        self.events.append(event)

    async def snapshot(self, job_id: str, limit: int = 1_000):
        raise NotImplementedError


class _StreamingGenerator:
    model_id = "test/model"
    model_revision = "a" * 40

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.prepared = False

    async def prepare(self) -> None:
        self.prepared = True

    async def generate_stream(self, system, user, maximum, observer):
        observer("a" * 100)
        observer("b" * 40 + "\n")
        if self.error is not None:
            raise self.error
        return "a" * 100 + "b" * 40 + "\n"

    async def generate(self, system, user, maximum):
        raise AssertionError("stream path expected")


class _FallbackGenerator:
    model_id = "test/fallback"
    model_revision = "b" * 40

    async def prepare(self) -> None:
        return None

    async def generate(self, system, user, maximum):
        return "fallback"


class ObservedTextGeneratorTest(unittest.TestCase):
    def test_persists_started_buffered_deltas_and_completed(self) -> None:
        delegate = _StreamingGenerator()
        streams = _Streams()
        generator = ObservedTextGenerator(
            delegate,
            "job-" + "a" * 32,
            "CLAIM_DRAFT",
            streams,
            _Clock(),
            _Ids(),
        )

        asyncio.run(generator.prepare())
        result = asyncio.run(generator.generate("system", "user", 256))

        self.assertTrue(delegate.prepared)
        self.assertEqual(generator.model_id, "test/model")
        self.assertEqual(generator.model_revision, "a" * 40)
        self.assertEqual(result, "a" * 100 + "b" * 40 + "\n")
        self.assertEqual(
            [event.kind for event in streams.events],
            [
                ModelStreamEventKind.STARTED,
                ModelStreamEventKind.DELTA,
                ModelStreamEventKind.COMPLETED,
            ],
        )
        self.assertEqual(streams.events[1].text, result)

    def test_records_failure_and_does_not_mask_generation_error(self) -> None:
        streams = _Streams()
        generator = ObservedTextGenerator(
            _StreamingGenerator(revision_error("TOKEN_BUDGET_EXCEEDED")),
            "job-" + "b" * 32,
            "TASK_PLAN",
            streams,
            _Clock(),
            _Ids(),
        )

        with self.assertRaises(ApplicationError):
            asyncio.run(generator.generate("system", "user", 256))

        self.assertEqual(streams.events[-1].kind, ModelStreamEventKind.FAILED)
        self.assertEqual(streams.events[-1].error_code, "TOKEN_BUDGET_EXCEEDED")

    def test_supports_non_streaming_delegate_and_ignores_observer_io_failure(self) -> None:
        streams = _Streams(fail=True)
        generator = ObservedTextGenerator(
            _FallbackGenerator(),
            "job-" + "c" * 32,
            "TASK_OUTPUT",
            streams,
            _Clock(),
            _Ids(),
        )

        result = asyncio.run(generator.generate("system", "user", 256))

        self.assertEqual(result, "fallback")
        self.assertEqual(streams.events, [])


if __name__ == "__main__":
    unittest.main()
