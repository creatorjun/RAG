from __future__ import annotations

import asyncio
import unittest

from enterprise_rag.application.dto.tasks import (
    TaskAttemptResultDto,
    TaskOutputDto,
    TaskPlanExecutionDto,
    TaskSectionOutputDto,
    TaskValidationReportDto,
)
from enterprise_rag.application.use_cases.execute_resumable_task_plan import (
    ExecuteResumableTaskPlan,
)
from enterprise_rag.domain.errors import ApplicationError, revision_error


class _Results:
    def __init__(self) -> None:
        self.values = {}

    async def load_output(self, job_id, task_id, attempt):
        value = self.values.get((task_id, attempt))
        if value is None:
            raise revision_error("JOB_ARTIFACT_NOT_FOUND")
        return value[0]

    async def load_validation(self, job_id, task_id, attempt):
        value = self.values.get((task_id, attempt))
        if value is None:
            raise revision_error("JOB_ARTIFACT_NOT_FOUND")
        return value[1]


class _Attempts:
    def __init__(self, results: _Results, generated) -> None:
        self.results = results
        self.generated = list(generated)
        self.calls = []

    async def execute(self, job_id, packet, ledger, evidence, attempt, previous):
        self.calls.append(attempt)
        output, validation = self.generated.pop(0)
        self.results.values[(packet.task_id, attempt)] = (output, validation)
        return TaskAttemptResultDto(attempt, output, validation)


def _output(task_id: str) -> TaskOutputDto:
    return TaskOutputDto(
        task_id,
        (TaskSectionOutputDto("section", "Section", "body", ("claim",), ("evidence",)),),
        (),
        "TASK_COMPLETE",
    )


class ExecuteResumableTaskPlanTest(unittest.TestCase):
    def test_reuses_legacy_failed_attempt_without_regeneration(self) -> None:
        task_id = "task-one"
        output = _output(task_id)
        failed = TaskValidationReportDto(task_id, False, ("MISSING",))
        results = _Results()
        results.values[(task_id, 1)] = (output, failed)
        attempts = _Attempts(results, ())
        runner = ExecuteResumableTaskPlan(attempts, results, 3)

        class _Packet:
            def __init__(self) -> None:
                self.task_id = task_id

        class _Plan:
            tasks = (_Packet(),)

        execution = asyncio.run(
            runner.execute("job-" + "a" * 32, _Plan(), object(), object())  # type: ignore[arg-type]
        )
        self.assertIsInstance(execution, TaskPlanExecutionDto)
        self.assertTrue(execution.complete)
        self.assertEqual(execution.total_attempt_count, 1)
        self.assertEqual(execution.validations, (TaskValidationReportDto(task_id, True, ()),))
        self.assertEqual(attempts.calls, [])

    def test_rejects_attempt_gap(self) -> None:
        task_id = "task-one"
        output = _output(task_id)
        valid = TaskValidationReportDto(task_id, True, ())
        results = _Results()
        results.values[(task_id, 2)] = (output, valid)
        runner = ExecuteResumableTaskPlan(_Attempts(results, ()), results, 3)
        with self.assertRaises(ApplicationError):
            asyncio.run(runner._existing_attempts("job-" + "a" * 32, task_id))


if __name__ == "__main__":
    unittest.main()
