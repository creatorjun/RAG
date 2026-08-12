from __future__ import annotations

from typing import Any

from enterprise_rag.application.dto.claims import ClaimRelationDto
from enterprise_rag.application.dto.tasks import (
    ClaimCoverageDto,
    CoverageMatrixDto,
    EvidenceCoverageDto,
    TaskPacketDto,
    TaskPlanDto,
)
from enterprise_rag.application.ports.job_artifacts import JobArtifactRepositoryPort
from enterprise_rag.domain.claims import ClaimRelationType
from enterprise_rag.domain.errors import revision_error

_TASK_PLAN_PATH = "control/task-plan.json"


class FilesystemTaskPlanRepository:
    def __init__(self, artifacts: JobArtifactRepositoryPort) -> None:
        self._artifacts = artifacts

    async def save(self, job_id: str, plan: TaskPlanDto) -> str:
        return await self._artifacts.write_json_once(
            job_id,
            _TASK_PLAN_PATH,
            {
                "schema_version": 1,
                "job_id": job_id,
                "tasks": [self._serialize_task(task) for task in plan.tasks],
                "coverage": {
                    "source_claim_count": plan.coverage.source_claim_count,
                    "source_evidence_count": plan.coverage.source_evidence_count,
                    "claim_coverage": [
                        {
                            "claim_id": entry.claim_id,
                            "owner_task_id": entry.owner_task_id,
                        }
                        for entry in plan.coverage.claim_coverage
                    ],
                    "evidence_coverage": [
                        {
                            "evidence_id": entry.evidence_id,
                            "task_ids": list(entry.task_ids),
                        }
                        for entry in plan.coverage.evidence_coverage
                    ],
                },
            },
        )

    async def load(self, job_id: str) -> TaskPlanDto:
        value = await self._artifacts.read_json(job_id, _TASK_PLAN_PATH)
        try:
            if value.get("schema_version") != 1 or value.get("job_id") != job_id:
                raise ValueError("invalid task plan manifest")
            coverage_value = self._mapping(value["coverage"])
            tasks = tuple(self._task(item) for item in self._list(value["tasks"]))
            coverage = CoverageMatrixDto(
                claim_coverage=tuple(
                    ClaimCoverageDto(
                        str(self._mapping(item)["claim_id"]),
                        str(self._mapping(item)["owner_task_id"]),
                    )
                    for item in self._list(coverage_value["claim_coverage"])
                ),
                evidence_coverage=tuple(
                    EvidenceCoverageDto(
                        str(self._mapping(item)["evidence_id"]),
                        self._strings(self._mapping(item)["task_ids"]),
                    )
                    for item in self._list(coverage_value["evidence_coverage"])
                ),
                source_claim_count=self._integer(coverage_value["source_claim_count"]),
                source_evidence_count=self._integer(
                    coverage_value["source_evidence_count"]
                ),
            )
            return TaskPlanDto(tasks, coverage)
        except (KeyError, TypeError, ValueError) as error:
            raise revision_error("TASK_PLAN_INVALID", {"job_id": job_id}) from error

    @staticmethod
    def _serialize_task(task: TaskPacketDto) -> dict[str, object]:
        return {
            "task_id": task.task_id,
            "title": task.title,
            "objective": task.objective,
            "owned_claim_ids": list(task.owned_claim_ids),
            "context_claim_ids": list(task.context_claim_ids),
            "allowed_evidence_ids": list(task.allowed_evidence_ids),
            "relations": [
                {
                    "left_claim_id": relation.left_claim_id,
                    "right_claim_id": relation.right_claim_id,
                    "relation": relation.relation.value,
                }
                for relation in task.relations
            ],
            "required_sections": list(task.required_sections),
            "depends_on_task_ids": list(task.depends_on_task_ids),
            "output_schema_version": task.output_schema_version,
        }

    @classmethod
    def _task(cls, value: Any) -> TaskPacketDto:
        item = cls._mapping(value)
        return TaskPacketDto(
            task_id=str(item["task_id"]),
            title=str(item["title"]),
            objective=str(item["objective"]),
            owned_claim_ids=cls._strings(item["owned_claim_ids"]),
            context_claim_ids=cls._strings(item["context_claim_ids"]),
            allowed_evidence_ids=cls._strings(item["allowed_evidence_ids"]),
            relations=tuple(
                cls._relation(relation) for relation in cls._list(item["relations"])
            ),
            required_sections=cls._strings(item["required_sections"]),
            depends_on_task_ids=cls._strings(item["depends_on_task_ids"]),
            output_schema_version=cls._integer(item["output_schema_version"]),
        )

    @classmethod
    def _relation(cls, value: Any) -> ClaimRelationDto:
        item = cls._mapping(value)
        return ClaimRelationDto(
            str(item["left_claim_id"]),
            str(item["right_claim_id"]),
            ClaimRelationType(str(item["relation"])),
        )

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("expected object")
        return value

    @staticmethod
    def _list(value: Any) -> list[Any]:
        if not isinstance(value, list):
            raise ValueError("expected list")
        return value

    @classmethod
    def _strings(cls, value: Any) -> tuple[str, ...]:
        values = cls._list(value)
        if any(not isinstance(item, str) for item in values):
            raise ValueError("expected strings")
        return tuple(values)

    @staticmethod
    def _integer(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("expected integer")
        return int(value)
