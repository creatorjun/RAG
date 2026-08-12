from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from enterprise_rag.domain.jobs import DocumentJob, DocumentJobState
from enterprise_rag.domain.value_objects import Sha256Digest


@dataclass(frozen=True, slots=True)
class CreateDocumentJobDto:
    source_root: str
    instruction: str
    output_relative_path: str
    pipeline_fingerprint: str

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
