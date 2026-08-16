from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from enterprise_rag.application.dto.claims import ClaimRelationDto

_TASK_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")


@dataclass(frozen=True, slots=True)
class TaskDefinitionDto:
    task_id: str
    title: str
    objective: str
    owned_claim_ids: tuple[str, ...]
    required_sections: tuple[str, ...]
    depends_on_task_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _TASK_ID_PATTERN.fullmatch(self.task_id):
            raise ValueError("invalid task ID")
        if not self.title.strip() or not self.objective.strip():
            raise ValueError("task title and objective are required")
        if not self.owned_claim_ids or len(self.owned_claim_ids) != len(
            set(self.owned_claim_ids)
        ):
            raise ValueError("task owned claims must be non-empty and unique")
        if not self.required_sections or len(self.required_sections) != len(
            set(self.required_sections)
        ):
            raise ValueError("task required sections must be non-empty and unique")
        if any(not section.strip() for section in self.required_sections):
            raise ValueError("task section must not be empty")
        if self.task_id in self.depends_on_task_ids or len(self.depends_on_task_ids) != len(
            set(self.depends_on_task_ids)
        ):
            raise ValueError("invalid task dependency")


@dataclass(frozen=True, slots=True)
class TaskPacketDto:
    task_id: str
    title: str
    objective: str
    owned_claim_ids: tuple[str, ...]
    context_claim_ids: tuple[str, ...]
    allowed_evidence_ids: tuple[str, ...]
    relations: tuple[ClaimRelationDto, ...]
    required_sections: tuple[str, ...]
    depends_on_task_ids: tuple[str, ...]
    output_schema_version: int = 1

    def __post_init__(self) -> None:
        if not _TASK_ID_PATTERN.fullmatch(self.task_id) or self.output_schema_version != 1:
            raise ValueError("invalid task packet")
        if not self.owned_claim_ids or not self.allowed_evidence_ids:
            raise ValueError("task packet requires claims and evidence")
        collections = (
            self.owned_claim_ids,
            self.context_claim_ids,
            self.allowed_evidence_ids,
            self.required_sections,
            self.depends_on_task_ids,
        )
        if any(len(values) != len(set(values)) for values in collections):
            raise ValueError("task packet collections must be unique")
        if set(self.owned_claim_ids) & set(self.context_claim_ids):
            raise ValueError("owned and context claims must be distinct")


@dataclass(frozen=True, slots=True)
class ClaimCoverageDto:
    claim_id: str
    owner_task_id: str


@dataclass(frozen=True, slots=True)
class EvidenceCoverageDto:
    evidence_id: str
    task_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.task_ids or len(self.task_ids) != len(set(self.task_ids)):
            raise ValueError("evidence coverage requires unique tasks")


@dataclass(frozen=True, slots=True)
class CoverageMatrixDto:
    claim_coverage: tuple[ClaimCoverageDto, ...]
    evidence_coverage: tuple[EvidenceCoverageDto, ...]
    source_claim_count: int
    source_evidence_count: int

    def __post_init__(self) -> None:
        if len(self.claim_coverage) != self.source_claim_count:
            raise ValueError("claim coverage is incomplete")
        if len(self.evidence_coverage) != self.source_evidence_count:
            raise ValueError("evidence coverage is incomplete")
        claim_ids = [entry.claim_id for entry in self.claim_coverage]
        evidence_ids = [entry.evidence_id for entry in self.evidence_coverage]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("duplicate claim coverage")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("duplicate evidence coverage")


@dataclass(frozen=True, slots=True)
class TaskPlanDto:
    tasks: tuple[TaskPacketDto, ...]
    coverage: CoverageMatrixDto

    def __post_init__(self) -> None:
        if not self.tasks:
            raise ValueError("task plan must contain tasks")
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("duplicate task ID")


@dataclass(frozen=True, slots=True)
class TaskSectionOutputDto:
    section_key: str
    heading: str
    markdown: str
    used_claim_ids: tuple[str, ...]
    used_evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.section_key.strip() or not self.heading.strip() or not self.markdown.strip():
            raise ValueError("task section content is required")
        if len(self.used_claim_ids) != len(set(self.used_claim_ids)) or len(
            self.used_evidence_ids
        ) != len(set(self.used_evidence_ids)):
            raise ValueError("task section references must be unique")


@dataclass(frozen=True, slots=True)
class TaskOutputDto:
    task_id: str
    sections: tuple[TaskSectionOutputDto, ...]
    conflict_claim_ids: tuple[str, ...]
    completion_marker: str

    def __post_init__(self) -> None:
        if not self.task_id or not self.sections:
            raise ValueError("task output requires task and sections")
        section_keys = [section.section_key for section in self.sections]
        if len(section_keys) != len(set(section_keys)):
            raise ValueError("duplicate task output section")
        if len(self.conflict_claim_ids) != len(set(self.conflict_claim_ids)):
            raise ValueError("duplicate conflict claim")


@dataclass(frozen=True, slots=True)
class TaskValidationReportDto:
    task_id: str
    valid: bool
    error_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.valid == bool(self.error_codes):
            raise ValueError("task validation status and errors are inconsistent")
        if len(self.error_codes) != len(set(self.error_codes)):
            raise ValueError("duplicate task validation error")


@dataclass(frozen=True, slots=True)
class TaskAttemptResultDto:
    attempt: int
    output: TaskOutputDto
    validation: TaskValidationReportDto

    def __post_init__(self) -> None:
        if not 1 <= self.attempt <= 3:
            raise ValueError("task attempt must be between one and three")
        if self.output.task_id != self.validation.task_id:
            raise ValueError("task attempt output and validation mismatch")


@dataclass(frozen=True, slots=True)
class TaskPlanExecutionDto:
    outputs: tuple[TaskOutputDto, ...]
    validations: tuple[TaskValidationReportDto, ...]
    total_attempt_count: int
    complete: bool

    def __post_init__(self) -> None:
        output_ids = [output.task_id for output in self.outputs]
        validation_ids = [report.task_id for report in self.validations]
        if len(output_ids) != len(set(output_ids)) or len(validation_ids) != len(
            set(validation_ids)
        ):
            raise ValueError("task plan execution contains duplicate tasks")
        if output_ids != validation_ids:
            raise ValueError("task plan execution output and validation mismatch")
        if self.total_attempt_count < len(self.outputs):
            raise ValueError("task attempt count is inconsistent")
        if self.complete and not self.outputs:
            raise ValueError("completed task plan contains no output")


@dataclass(frozen=True, slots=True)
class FinalQualityReportDto:
    valid: bool
    error_codes: tuple[str, ...]
    document_sha256: str
    source_document_count: int
    evidence_count: int
    claim_count: int
    task_count: int
    validated_task_count: int
    covered_claim_count: int
    covered_evidence_count: int

    def __post_init__(self) -> None:
        if self.valid == bool(self.error_codes):
            raise ValueError("final quality status and errors are inconsistent")
        if len(self.error_codes) != len(set(self.error_codes)):
            raise ValueError("duplicate final quality error")
        if not re.fullmatch(r"[0-9a-f]{64}", self.document_sha256):
            raise ValueError("invalid final document digest")
        counts = (
            self.source_document_count,
            self.evidence_count,
            self.claim_count,
            self.task_count,
            self.validated_task_count,
            self.covered_claim_count,
            self.covered_evidence_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("final quality counts must be non-negative")
        if self.validated_task_count > self.task_count:
            raise ValueError("validated task count exceeds task count")
        if self.covered_claim_count > self.claim_count:
            raise ValueError("covered claim count exceeds claim count")
        if self.covered_evidence_count > self.evidence_count:
            raise ValueError("covered evidence count exceeds evidence count")


@dataclass(frozen=True, slots=True)
class FinalDocumentCandidateDto:
    markdown: str
    quality: FinalQualityReportDto

    def __post_init__(self) -> None:
        if not self.markdown.strip():
            raise ValueError("final document candidate must not be empty")
        digest = hashlib.sha256(self.markdown.encode("utf-8")).hexdigest()
        if digest != self.quality.document_sha256:
            raise ValueError("final document candidate digest mismatch")
