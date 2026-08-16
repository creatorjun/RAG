from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from enterprise_rag.application.dto.claims import ClaimLedgerDto
from enterprise_rag.application.dto.tasks import (
    ClaimCoverageDto,
    CoverageMatrixDto,
    EvidenceCoverageDto,
    TaskDefinitionDto,
    TaskPacketDto,
    TaskPlanDto,
)
from enterprise_rag.domain.errors import revision_error


class BuildTaskPlan:
    def execute(
        self,
        ledger: ClaimLedgerDto,
        definitions: tuple[TaskDefinitionDto, ...],
    ) -> TaskPlanDto:
        if not definitions:
            raise revision_error("TASK_PLAN_INVALID")
        definitions = self._consolidate_same_topic_tasks(definitions)
        definitions_by_id = {definition.task_id: definition for definition in definitions}
        if len(definitions_by_id) != len(definitions):
            raise revision_error("TASK_PLAN_INVALID")
        self._validate_dependencies(definitions_by_id)

        claim_by_id = {claim.claim_id: claim for claim in ledger.claims}
        owners: dict[str, str] = {}
        for definition in definitions:
            for claim_id in definition.owned_claim_ids:
                if claim_id not in claim_by_id or claim_id in owners:
                    raise revision_error("COVERAGE_MATRIX_INCOMPLETE")
                owners[claim_id] = definition.task_id
        if set(owners) != set(claim_by_id):
            raise revision_error("COVERAGE_MATRIX_INCOMPLETE")

        evidence_used_by_claims = {
            evidence_id for claim in ledger.claims for evidence_id in claim.evidence_ids
        }
        if evidence_used_by_claims != set(ledger.reviewed_evidence_ids):
            raise revision_error("COVERAGE_MATRIX_INCOMPLETE")

        ordered_definitions = self._ordered_definitions(definitions, definitions_by_id)
        packets: list[TaskPacketDto] = []
        evidence_tasks: dict[str, set[str]] = {
            evidence_id: set() for evidence_id in ledger.reviewed_evidence_ids
        }
        for definition in ordered_definitions:
            owned = set(definition.owned_claim_ids)
            relevant_relations = tuple(
                relation
                for relation in ledger.relations
                if relation.left_claim_id in owned or relation.right_claim_id in owned
            )
            context = {
                claim_id
                for relation in relevant_relations
                for claim_id in (relation.left_claim_id, relation.right_claim_id)
                if claim_id not in owned
            }
            visible_claim_ids = owned | context
            allowed_evidence = {
                evidence_id
                for claim_id in visible_claim_ids
                for evidence_id in claim_by_id[claim_id].evidence_ids
            }
            for evidence_id in allowed_evidence:
                evidence_tasks[evidence_id].add(definition.task_id)
            try:
                packets.append(
                    TaskPacketDto(
                        task_id=definition.task_id,
                        title=definition.title.strip(),
                        objective=definition.objective.strip(),
                        owned_claim_ids=tuple(sorted(owned)),
                        context_claim_ids=tuple(sorted(context)),
                        allowed_evidence_ids=tuple(sorted(allowed_evidence)),
                        relations=relevant_relations,
                        required_sections=definition.required_sections,
                        depends_on_task_ids=definition.depends_on_task_ids,
                    )
                )
            except ValueError as error:
                raise revision_error("TASK_PLAN_INVALID") from error
        if any(not task_ids for task_ids in evidence_tasks.values()):
            raise revision_error("COVERAGE_MATRIX_INCOMPLETE")
        try:
            coverage = CoverageMatrixDto(
                claim_coverage=tuple(
                    ClaimCoverageDto(claim_id, owners[claim_id])
                    for claim_id in sorted(owners)
                ),
                evidence_coverage=tuple(
                    EvidenceCoverageDto(evidence_id, tuple(sorted(evidence_tasks[evidence_id])))
                    for evidence_id in sorted(evidence_tasks)
                ),
                source_claim_count=len(ledger.claims),
                source_evidence_count=len(ledger.reviewed_evidence_ids),
            )
            return TaskPlanDto(tuple(packets), coverage)
        except ValueError as error:
            raise revision_error("COVERAGE_MATRIX_INCOMPLETE") from error

    @classmethod
    def _consolidate_same_topic_tasks(
        cls,
        definitions: tuple[TaskDefinitionDto, ...],
    ) -> tuple[TaskDefinitionDto, ...]:
        """Merge identical chapter topics produced by independent planning batches.

        A large ledger is planned in bounded batches.  Without a global ownership pass,
        each batch can independently invent the same chapter and the final renderer then
        repeats that chapter.  Consolidation changes no Claim ownership: it only moves the
        already-owned Claims under the first canonical task for an identical normalized
        title and remaps dependencies.
        """

        groups: dict[str, list[TaskDefinitionDto]] = {}
        ordered_keys: list[str] = []
        for definition in definitions:
            key = cls._topic_key(definition.title)
            if key not in groups:
                groups[key] = []
                ordered_keys.append(key)
            groups[key].append(definition)

        representative_by_task = {
            definition.task_id: grouped[0].task_id
            for grouped in groups.values()
            for definition in grouped
        }
        consolidated: list[TaskDefinitionDto] = []
        for key in ordered_keys:
            grouped = groups[key]
            representative = grouped[0]
            claims = cls._ordered_unique(
                claim_id for definition in grouped for claim_id in definition.owned_claim_ids
            )
            sections = cls._ordered_unique(
                section for definition in grouped for section in definition.required_sections
            )
            dependencies = cls._ordered_unique(
                representative_by_task.get(dependency, dependency)
                for definition in grouped
                for dependency in definition.depends_on_task_ids
                if representative_by_task.get(dependency, dependency) != representative.task_id
            )
            objective = max(
                (definition.objective.strip() for definition in grouped),
                key=lambda value: (len(value), value),
            )
            consolidated.append(
                TaskDefinitionDto(
                    task_id=representative.task_id,
                    title=cls._clean_title(representative.title),
                    objective=objective,
                    owned_claim_ids=claims,
                    required_sections=sections,
                    depends_on_task_ids=dependencies,
                )
            )
        return tuple(consolidated)

    @staticmethod
    def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(values))

    @classmethod
    def _topic_key(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFKC", cls._clean_title(value)).casefold()
        return " ".join(normalized.split())

    @staticmethod
    def _clean_title(value: str) -> str:
        return re.sub(r"^\s{0,3}#{1,6}\s*", "", value).strip()

    @staticmethod
    def _validate_dependencies(
        definitions: dict[str, TaskDefinitionDto],
    ) -> None:
        known = set(definitions)
        if any(
            set(definition.depends_on_task_ids) - known
            for definition in definitions.values()
        ):
            raise revision_error("TASK_PLAN_INVALID")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise revision_error("TASK_PLAN_INVALID")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in definitions[task_id].depends_on_task_ids:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in definitions:
            visit(task_id)

    @staticmethod
    def _ordered_definitions(
        definitions: tuple[TaskDefinitionDto, ...],
        definitions_by_id: dict[str, TaskDefinitionDto],
    ) -> tuple[TaskDefinitionDto, ...]:
        ordered: list[TaskDefinitionDto] = []
        visited: set[str] = set()

        def append(task_id: str) -> None:
            if task_id in visited:
                return
            definition = definitions_by_id[task_id]
            for dependency in definition.depends_on_task_ids:
                append(dependency)
            visited.add(task_id)
            ordered.append(definition)

        for definition in definitions:
            append(definition.task_id)
        return tuple(ordered)
