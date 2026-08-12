from __future__ import annotations

import unittest

from enterprise_rag.application.dto.progress import ProgressEventDto
from enterprise_rag.application.progress import ProgressReporter


class ProgressReporterTest(unittest.TestCase):
    def test_emits_ordered_events_with_counts(self) -> None:
        events: list[ProgressEventDto] = []
        reporter = ProgressReporter(events.append, "job-" + "a" * 32)
        first = reporter.emit(None, "INSPECTING", "원본 분석 중")
        second = reporter.emit(10, "SNAPSHOTTING", "스냅샷 생성 중", 1, 3, "documents")
        self.assertEqual(first.sequence, 1)
        self.assertIsNone(first.percentage)
        self.assertEqual(second.sequence, 2)
        self.assertEqual(second.counter_name, "documents")
        self.assertEqual(events, [first, second])

    def test_rejects_decreasing_percentage_and_invalid_counter(self) -> None:
        reporter = ProgressReporter()
        reporter.emit(20, "PLANNING", "계획 중")
        with self.assertRaises(ValueError):
            reporter.emit(19, "PLANNING", "계획 중")
        with self.assertRaises(ValueError):
            ProgressEventDto(10, "stage", "message", 2, 1)


if __name__ == "__main__":
    unittest.main()
