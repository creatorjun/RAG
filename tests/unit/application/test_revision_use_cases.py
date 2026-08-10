# tests/unit/application/test_revision_use_cases.py
from __future__ import annotations

import asyncio
import unittest

from enterprise_rag.application.dto.revision import FolderComparisonDto, RevisionRunDto
from enterprise_rag.application.use_cases.compare_revision_run import CompareRevisionRun
from enterprise_rag.application.use_cases.finalize_revision_run import FinalizeRevisionRun
from enterprise_rag.application.use_cases.prepare_revision_run import PrepareRevisionRun
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.domain.revision import RevisionRunState


class _FakeWorkspace:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def prepare_run(self, run_id: str) -> RevisionRunDto:
        self.calls.append(("prepare", run_id))
        return self._run(run_id, RevisionRunState.PREPARED)

    async def compare_run(self, run_id: str) -> FolderComparisonDto:
        self.calls.append(("compare", run_id))
        return FolderComparisonDto(run_id, "cmp-1", "2026-08-10T00:00:00Z", (), "a" * 64)

    async def finalize_run(self, run_id: str) -> RevisionRunDto:
        self.calls.append(("finalize", run_id))
        return self._run(run_id, RevisionRunState.FINALIZED)

    @staticmethod
    def _run(run_id: str, state: RevisionRunState) -> RevisionRunDto:
        return RevisionRunDto(
            run_id,
            state,
            "a" * 64,
            1,
            f"runs/{run_id}/documents",
            "2026-08-10T00:00:00Z",
            "2026-08-10T00:01:00Z" if state is RevisionRunState.FINALIZED else None,
        )


class RevisionUseCaseTest(unittest.TestCase):
    def test_delegates_validated_run_id(self) -> None:
        workspace = _FakeWorkspace()
        run_id = "20260810t120000z-oracle"
        prepared = asyncio.run(PrepareRevisionRun(workspace).execute(run_id))
        compared = asyncio.run(CompareRevisionRun(workspace).execute(run_id))
        finalized = asyncio.run(FinalizeRevisionRun(workspace).execute(run_id))
        self.assertEqual(prepared.state, RevisionRunState.PREPARED)
        self.assertEqual(compared.run_id, run_id)
        self.assertEqual(finalized.state, RevisionRunState.FINALIZED)
        self.assertEqual(
            workspace.calls,
            [("prepare", run_id), ("compare", run_id), ("finalize", run_id)],
        )

    def test_rejects_invalid_run_id_before_port_call(self) -> None:
        workspace = _FakeWorkspace()
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(PrepareRevisionRun(workspace).execute("../escape"))
        self.assertEqual(captured.exception.code, "INVALID_RUN_ID")
        self.assertEqual(workspace.calls, [])


if __name__ == "__main__":
    unittest.main()
