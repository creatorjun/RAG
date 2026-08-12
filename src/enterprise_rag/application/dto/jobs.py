from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from enterprise_rag.domain.jobs import DocumentJob, DocumentJobState
from enterprise_rag.domain.value_objects import Sha256Digest


@dataclass(frozen=True, slots=True)
class JobExecutionSettingsDto:
    output_root: str
    model_id: str
    model_revision: str
    context_tokens: int
    max_output_tokens: int
    additional_system_prompt: str
    prompt_fingerprint: str
    max_task_attempts: int
    offline_mode: bool
    notify_on_completion: bool

    def __post_init__(self) -> None:
        if not self.output_root or not Path(self.output_root).is_absolute():
            raise ValueError("job output root must be absolute")
        if not self.model_id or "/" not in self.model_id:
            raise ValueError("job model ID is invalid")
        if not re.fullmatch(r"[0-9a-f]{40}", self.model_revision):
            raise ValueError("job model revision must be a commit SHA")
        Sha256Digest(self.prompt_fingerprint)
        if (
            self.context_tokens < 4_096
            or not 512 <= self.max_output_tokens <= self.context_tokens - 512
        ):
            raise ValueError("job model token settings are invalid")
        if len(self.additional_system_prompt) > 20_000:
            raise ValueError("job additional system prompt is too long")
        if not 1 <= self.max_task_attempts <= 3:
            raise ValueError("job task attempt setting is invalid")


@dataclass(frozen=True, slots=True)
class CreateDocumentJobDto:
    source_root: str
    instruction: str
    output_relative_path: str
    pipeline_fingerprint: str
    execution_settings: JobExecutionSettingsDto | None = None

    def __post_init__(self) -> None:
        if not self.source_root or not Path(self.source_root).is_absolute():
            raise ValueError("document job source root must be absolute")
        if not self.instruction.strip() or len(self.instruction) > 20_000:
            raise ValueError("document job instruction is invalid")
        output = PurePosixPath(self.output_relative_path)
        if (
            not self.output_relative_path
            or output.is_absolute()
            or any(part in {"", ".", ".."} for part in output.parts)
            or output.suffix.lower() != ".md"
        ):
            raise ValueError("document job output path is invalid")
        Sha256Digest(self.pipeline_fingerprint)


@dataclass(frozen=True, slots=True)
class StoredDocumentJobDefinitionDto:
    job_id: str
    request: CreateDocumentJobDto

    def __post_init__(self) -> None:
        if not re.fullmatch(r"job-[0-9a-f]{32}", self.job_id):
            raise ValueError("stored document job ID is invalid")
        if self.request.execution_settings is None:
            raise ValueError("stored document job execution settings are required")


@dataclass(frozen=True, slots=True)
class DocumentJobDto:
    job_id: str
    state: DocumentJobState
    last_event_sequence: int
    last_percentage: int

    @classmethod
    def from_domain(cls, job: DocumentJob) -> DocumentJobDto:
        return cls(
            job_id=job.job_id,
            state=job.state,
            last_event_sequence=job.last_event_sequence,
            last_percentage=job.last_percentage,
        )


@dataclass(frozen=True, slots=True)
class DocumentJobLaunchDto:
    job: DocumentJobDto
    process_id: int

    def __post_init__(self) -> None:
        if self.process_id < 1:
            raise ValueError("document job process ID must be positive")
