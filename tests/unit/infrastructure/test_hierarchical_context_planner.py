# tests/unit/infrastructure/test_hierarchical_context_planner.py
from __future__ import annotations

import unittest

from enterprise_rag.application.dto.long_document import LongTextChunkDto, SourceSpanDto
from enterprise_rag.domain.context_budget import TokenBudget
from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.infrastructure.planning.hierarchical_context_planner import (
    HierarchicalContextPlanner,
)


def _chunk(index: int, token_count: int = 800) -> LongTextChunkDto:
    chunk_id = f"chunk-{index:04d}"
    return LongTextChunkDto(
        chunk_id=chunk_id,
        revision_id="revision-1",
        ordinal=index,
        primary_text="text",
        context_prefix="",
        model_input="text",
        model_token_count=token_count,
        content_sha256="a" * 64,
        primary_span=SourceSpanDto(index, index + 1),
        context_span=None,
        previous_chunk_id=None,
        next_chunk_id=None,
    )


class HierarchicalContextPlannerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = HierarchicalContextPlanner()
        self.map_budget = TokenBudget(4096, 512, 512, 256, 0.8)
        self.reduce_budget = TokenBudget(4096, 512, 768, 256, 0.8)

    def test_plans_every_item_once_across_multiple_reduce_rounds(self) -> None:
        chunks = tuple(_chunk(index) for index in range(100))
        plan = self.planner.plan(chunks, self.map_budget, self.reduce_budget, 128, 8)
        map_item_ids = [item_id for batch in plan.map_batches for item_id in batch.item_ids]
        self.assertEqual(map_item_ids, [chunk.chunk_id for chunk in chunks])
        self.assertEqual(len(map_item_ids), len(set(map_item_ids)))
        self.assertGreater(len(plan.map_batches), 1)
        self.assertGreater(len(plan.reduce_rounds), 1)
        self.assertTrue(plan.complete)
        self.assertIsNotNone(plan.root_result_id)
        previous_ids = [batch.result_id for batch in plan.map_batches]
        for reduce_round in plan.reduce_rounds:
            actual_ids = [item_id for batch in reduce_round for item_id in batch.item_ids]
            self.assertEqual(actual_ids, previous_ids)
            self.assertEqual(len(actual_ids), len(set(actual_ids)))
            previous_ids = [batch.result_id for batch in reduce_round]
        self.assertEqual(previous_ids, [plan.root_result_id])
        for batch in plan.map_batches:
            self.assertLessEqual(batch.total_planned_tokens, batch.maximum_context_tokens)
        for reduce_round in plan.reduce_rounds:
            for batch in reduce_round:
                self.assertLessEqual(batch.total_planned_tokens, batch.maximum_context_tokens)

    def test_rejects_duplicate_and_oversized_items(self) -> None:
        duplicate = (_chunk(1), _chunk(1))
        with self.assertRaises(ApplicationError) as duplicate_error:
            self.planner.plan(duplicate, self.map_budget, self.reduce_budget, 128, 8)
        self.assertEqual(duplicate_error.exception.code, "DUPLICATE_PLAN_ITEM")
        oversized = (_chunk(1, self.map_budget.content_capacity_tokens + 1),)
        with self.assertRaises(ApplicationError) as budget_error:
            self.planner.plan(oversized, self.map_budget, self.reduce_budget, 128, 8)
        self.assertEqual(budget_error.exception.code, "TOKEN_BUDGET_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
