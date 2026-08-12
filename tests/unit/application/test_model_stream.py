from __future__ import annotations

import unittest
from datetime import datetime, timezone

from enterprise_rag.application.dto.model_stream import (
    ModelStreamEventDto,
    ModelStreamEventKind,
    ModelStreamSnapshotDto,
)


def _event(**changes: object) -> ModelStreamEventDto:
    values = {
        "job_id": "job-" + "a" * 32,
        "sequence": 1,
        "generation_id": "generation-" + "b" * 32,
        "stage": "CLAIM_DRAFT",
        "kind": ModelStreamEventKind.DELTA,
        "text": "token",
        "occurred_at": datetime(2026, 8, 12, tzinfo=timezone.utc),
        "error_code": None,
    }
    values.update(changes)
    return ModelStreamEventDto(**values)  # type: ignore[arg-type]


class ModelStreamDtoTest(unittest.TestCase):
    def test_rejects_invalid_event_contracts(self) -> None:
        invalid = (
            {"sequence": 0},
            {"generation_id": "bad"},
            {"stage": ""},
            {"text": "x" * 4_097},
            {
                "occurred_at": datetime(
                    2026, 8, 12, tzinfo=timezone.utc
                ).replace(tzinfo=None)
            },
            {"text": ""},
            {"error_code": "INVALID"},
            {"kind": ModelStreamEventKind.STARTED},
            {
                "kind": ModelStreamEventKind.FAILED,
                "text": "",
                "error_code": None,
            },
            {
                "kind": ModelStreamEventKind.COMPLETED,
                "text": "",
                "error_code": "INVALID",
            },
        )
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _event(**changes)

    def test_validates_snapshot_order_uniqueness_and_latest_sequence(self) -> None:
        first = _event()
        second = _event(sequence=2)
        self.assertEqual(
            ModelStreamSnapshotDto((first, second), 2).latest_sequence,
            2,
        )
        with self.assertRaises(ValueError):
            ModelStreamSnapshotDto((second, first), 2)
        with self.assertRaises(ValueError):
            ModelStreamSnapshotDto((first, first), 1)
        with self.assertRaises(ValueError):
            ModelStreamSnapshotDto((second,), 1)


if __name__ == "__main__":
    unittest.main()
