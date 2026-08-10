# src/enterprise_rag/infrastructure/planning/hierarchical_context_planner.py
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from enterprise_rag.application.dto.long_document import (
    ContextBatchDto,
    HierarchicalContextPlanDto,
    LongTextChunkDto,
)
from enterprise_rag.domain.context_budget import TokenBudget
from enterprise_rag.domain.errors import revision_error


@dataclass(frozen=True, slots=True)
class _PlanItem:
    item_id: str
    token_count: int


class HierarchicalContextPlanner:
    def plan(
        self,
        chunks: tuple[LongTextChunkDto, ...],
        map_budget: TokenBudget,
        reduce_budget: TokenBudget,
        item_overhead_tokens: int,
        separator_tokens: int,
    ) -> HierarchicalContextPlanDto:
        if item_overhead_tokens < 0 or separator_tokens < 0:
            raise ValueError("batch overhead tokens must be non-negative")
        map_items = tuple(_PlanItem(chunk.chunk_id, chunk.model_token_count) for chunk in chunks)
        map_batches = self._pack(
            map_items,
            map_budget,
            item_overhead_tokens,
            separator_tokens,
            "map",
            0,
        )
        self._validate_level(map_items, map_batches)
        if not map_batches:
            return HierarchicalContextPlanDto((), (), 0, None, True)
        previous = tuple(
            _PlanItem(batch.result_id, map_budget.max_output_tokens) for batch in map_batches
        )
        reduce_rounds: list[tuple[ContextBatchDto, ...]] = []
        round_ordinal = 1
        while len(previous) > 1:
            batches = self._pack(
                previous,
                reduce_budget,
                item_overhead_tokens,
                separator_tokens,
                "reduce",
                round_ordinal,
            )
            self._validate_level(previous, batches)
            if len(batches) >= len(previous):
                raise revision_error("TOKEN_BUDGET_EXCEEDED", {"stage": "reduce"})
            reduce_rounds.append(batches)
            previous = tuple(
                _PlanItem(batch.result_id, reduce_budget.max_output_tokens) for batch in batches
            )
            round_ordinal += 1
        return HierarchicalContextPlanDto(
            map_batches=map_batches,
            reduce_rounds=tuple(reduce_rounds),
            source_item_count=len(map_items),
            root_result_id=previous[0].item_id,
            complete=True,
        )

    def _pack(
        self,
        items: tuple[_PlanItem, ...],
        budget: TokenBudget,
        item_overhead_tokens: int,
        separator_tokens: int,
        purpose: str,
        round_ordinal: int,
    ) -> tuple[ContextBatchDto, ...]:
        identifiers = [item.item_id for item in items]
        if len(identifiers) != len(set(identifiers)):
            raise revision_error("DUPLICATE_PLAN_ITEM", {"stage": purpose})
        batches: list[ContextBatchDto] = []
        current: list[_PlanItem] = []
        current_tokens = 0
        for item in items:
            item_tokens = item.token_count + item_overhead_tokens
            budget.ensure_fits(item_tokens)
            incremental = item_tokens + (separator_tokens if current else 0)
            if current and current_tokens + incremental > budget.content_capacity_tokens:
                batches.append(
                    self._batch(
                        current,
                        current_tokens,
                        budget,
                        purpose,
                        round_ordinal,
                        len(batches),
                    )
                )
                current = []
                current_tokens = 0
                incremental = item_tokens
            current.append(item)
            current_tokens += incremental
        if current:
            batches.append(
                self._batch(current, current_tokens, budget, purpose, round_ordinal, len(batches))
            )
        return tuple(batches)

    @staticmethod
    def _batch(
        items: list[_PlanItem],
        input_tokens: int,
        budget: TokenBudget,
        purpose: str,
        round_ordinal: int,
        batch_ordinal: int,
    ) -> ContextBatchDto:
        budget.ensure_fits(input_tokens)
        item_ids = tuple(item.item_id for item in items)
        identity = f"{purpose}\0{round_ordinal}\0{batch_ordinal}\0{'|'.join(item_ids)}"
        batch_id = f"sha256:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"
        result_identity = f"result\0{batch_id}"
        result_id = f"sha256:{hashlib.sha256(result_identity.encode('utf-8')).hexdigest()}"
        return ContextBatchDto(
            batch_id=batch_id,
            result_id=result_id,
            purpose=purpose,
            round_ordinal=round_ordinal,
            batch_ordinal=batch_ordinal,
            item_ids=item_ids,
            input_tokens=input_tokens,
            content_capacity_tokens=budget.content_capacity_tokens,
            total_planned_tokens=budget.total_tokens(input_tokens),
            maximum_context_tokens=budget.maximum_context_tokens,
        )

    @staticmethod
    def _validate_level(
        items: tuple[_PlanItem, ...],
        batches: tuple[ContextBatchDto, ...],
    ) -> None:
        expected = [item.item_id for item in items]
        actual = [item_id for batch in batches for item_id in batch.item_ids]
        if actual != expected or len(actual) != len(set(actual)):
            raise revision_error("DUPLICATE_PLAN_ITEM")
