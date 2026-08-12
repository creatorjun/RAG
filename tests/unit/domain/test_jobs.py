from __future__ import annotations

import unittest

from enterprise_rag.domain.jobs import DocumentJob, DocumentJobState


class DocumentJobTest(unittest.TestCase):
    def test_follows_normal_flow_and_completes_at_one_hundred_percent(self) -> None:
        job = DocumentJob("job-" + "a" * 32)
        normal_flow = (
            DocumentJobState.INSPECTING,
            DocumentJobState.SNAPSHOTTING,
            DocumentJobState.EXTRACTING_EVIDENCE,
            DocumentJobState.BUILDING_CLAIMS,
            DocumentJobState.PLANNING,
            DocumentJobState.RUNNING_TASKS,
            DocumentJobState.VALIDATING_TASKS,
            DocumentJobState.ASSEMBLING,
            DocumentJobState.VALIDATING_FINAL,
            DocumentJobState.PUBLISHING,
            DocumentJobState.COMPLETED,
        )
        for target in normal_flow:
            job = job.transition(target)
        self.assertEqual(job.state, DocumentJobState.COMPLETED)
        self.assertEqual(job.last_percentage, 100)
        self.assertTrue(job.state.terminal)

    def test_rejects_skipped_transition_and_terminal_progress(self) -> None:
        job = DocumentJob("job-" + "b" * 32)
        with self.assertRaises(ValueError):
            job.transition(DocumentJobState.RUNNING_TASKS)
        cancelling = job.transition(DocumentJobState.CANCELLING)
        cancelled = cancelling.transition(DocumentJobState.CANCELLED)
        with self.assertRaises(ValueError):
            cancelled.record_progress(1, 10)

    def test_progress_sequence_and_percentage_are_monotonic(self) -> None:
        job = DocumentJob("job-" + "c" * 32).transition(DocumentJobState.INSPECTING)
        job = job.record_progress(1, None)
        job = job.record_progress(2, 10)
        with self.assertRaises(ValueError):
            job.record_progress(4, 20)
        with self.assertRaises(ValueError):
            job.record_progress(3, 9)

    def test_needs_attention_resumes_only_at_safe_boundaries(self) -> None:
        job = DocumentJob(
            "job-" + "d" * 32,
            state=DocumentJobState.VALIDATING_TASKS,
        )
        attention = job.transition(DocumentJobState.NEEDS_ATTENTION)
        self.assertEqual(
            attention.transition(DocumentJobState.RUNNING_TASKS).state,
            DocumentJobState.RUNNING_TASKS,
        )
        with self.assertRaises(ValueError):
            attention.transition(DocumentJobState.PUBLISHING)

    def test_failed_job_can_be_explicitly_requeued_without_losing_progress(self) -> None:
        failed = DocumentJob(
            "job-" + "e" * 32,
            DocumentJobState.FAILED,
            last_event_sequence=3,
            last_percentage=30,
        )

        requeued = failed.transition(DocumentJobState.CREATED)

        self.assertEqual(requeued.state, DocumentJobState.CREATED)
        self.assertEqual(requeued.last_event_sequence, 3)
        self.assertEqual(requeued.last_percentage, 30)


if __name__ == "__main__":
    unittest.main()
