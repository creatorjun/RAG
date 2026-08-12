from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from enterprise_rag.application.dto.long_document import ChunkingConfigDto
from enterprise_rag.application.use_cases.integrate_documents import IntegrateDocuments
from enterprise_rag.domain.context_budget import TokenBudget
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.infrastructure.chunking.structure_aware_text_chunker import (
    StructureAwareTextChunker,
)
from enterprise_rag.infrastructure.planning.hierarchical_context_planner import (
    HierarchicalContextPlanner,
)
from enterprise_rag.infrastructure.sources.before_text_source import BeforeTextDocumentSource
from enterprise_rag.infrastructure.tokenization.conservative_utf8 import (
    ConservativeUtf8TokenCounter,
)
from enterprise_rag.infrastructure.workspace.folder_revision_workspace import (
    FolderRevisionWorkspace,
)
from enterprise_rag.infrastructure.workspace.folder_tree_comparator import FolderTreeComparator


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 11, 3, 0, 0, tzinfo=timezone.utc)


class _SequenceIdGenerator:
    def __init__(self) -> None:
        self._value = 0

    def new_id(self) -> str:
        self._value += 1
        return f"{self._value:032x}"


class _FakeTextGenerator:
    model_id = "test/local-model"
    model_revision = "a" * 40

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def prepare(self) -> None:
        return None

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        self.prompts.append(user_prompt)
        if "최종본" in user_prompt:
            return """# 사내 기술 통합 가이드

## 전제조건

테스트 전제조건입니다. [source:guide.md / 0]

## 통합 절차

두 문서를 통합했습니다. [source:guide.md] [source:settings.yaml]

## 검증

결과를 검증합니다. [source:guide.md]

## 장애 복구

장애 시 복구합니다. [source:guide.md]

## 보안

비밀을 노출하지 않습니다. [source:settings.yaml]

<!-- ENTERPRISE_RAG_COMPLETE -->
"""
        return """근거 노트 [source:guide.md] [source:settings.yaml]
<!-- ENTERPRISE_RAG_COMPLETE -->"""


class _IncompleteTextGenerator:
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        return "잘린 모델 출력 [source:guide.md"


class DocumentIntegrationPipelineTest(unittest.TestCase):
    def test_rejects_generation_without_completion_marker(self) -> None:
        use_case = object.__new__(IntegrateDocuments)
        use_case._generator = _IncompleteTextGenerator()
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(use_case._generate("prompt", 128))
        self.assertEqual(captured.exception.code, "MODEL_OUTPUT_INCOMPLETE")

    def test_creates_integrated_document_and_comparison_in_one_use_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            before = root / "before"
            after = root / "after"
            before.mkdir()
            after.mkdir()
            (before / "guide.md").write_text(
                "# 운영 절차\n서비스를 시작하고 상태를 확인한다.\n",
                encoding="utf-8",
            )
            (before / "settings.yaml").write_text(
                "service:\n  enabled: true\n",
                encoding="utf-8",
            )
            clock = _FixedClock()
            ids = _SequenceIdGenerator()
            workspace = FolderRevisionWorkspace(
                before,
                after,
                FolderTreeComparator(),
                clock,
                ids,
                1024 * 1024,
            )
            counter = ConservativeUtf8TokenCounter()
            generator = _FakeTextGenerator()
            use_case = IntegrateDocuments(
                source=BeforeTextDocumentSource(before, 1024 * 1024),
                workspace=workspace,
                chunker=StructureAwareTextChunker(counter),
                planner=HierarchicalContextPlanner(),
                generator=generator,
                clock=clock,
                id_generator=ids,
                chunking_config=ChunkingConfigDto(
                    tokenizer_id=counter.identifier,
                    chunker_version="1",
                    target_tokens=256,
                    max_tokens=512,
                    minimum_tokens=16,
                    overlap_ratio=0.1,
                ),
                map_budget=TokenBudget(4096, 512, 512, 128, 0.8),
                reduce_budget=TokenBudget(4096, 512, 768, 128, 0.8),
                final_max_output_tokens=1024,
                item_overhead_tokens=64,
                separator_tokens=8,
            )

            progress = []
            result = asyncio.run(use_case.execute(progress=progress.append))

            run_root = after / "runs" / result.run.run_id
            output = run_root / "documents" / "integrated-technical-guide.md"
            self.assertTrue(output.is_file())
            self.assertIn("# 사내 기술 통합 가이드", output.read_text(encoding="utf-8"))
            self.assertIn("[source:guide.md]", output.read_text(encoding="utf-8"))
            self.assertNotIn("[source:guide.md / 0]", output.read_text(encoding="utf-8"))
            self.assertIn("## 원본 문서 목록", output.read_text(encoding="utf-8"))
            self.assertEqual(result.source_document_count, 2)
            self.assertEqual(result.comparison.counts["added"], 1)
            self.assertEqual(result.comparison.counts["unchanged"], 2)
            self.assertGreaterEqual(result.generation_count, 2)
            self.assertEqual(progress[0].percentage, 0)
            self.assertEqual(progress[-1].percentage, 100)
            self.assertEqual(progress[-1].stage, "completed")
            self.assertEqual(
                [item.percentage for item in progress],
                sorted(item.percentage for item in progress),
            )
            generation_progress = [
                item for item in progress if item.stage == "generating"
            ]
            self.assertEqual(generation_progress[-1].completed, result.generation_count)
            self.assertEqual(generation_progress[-1].total, result.generation_count)
            report = json.loads(
                (run_root / "_reports" / "synthesis.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["model_id"], generator.model_id)
            self.assertEqual(report["source_document_count"], 2)
            self.assertTrue((run_root / "_reports" / "comparison.json").is_file())


if __name__ == "__main__":
    unittest.main()
