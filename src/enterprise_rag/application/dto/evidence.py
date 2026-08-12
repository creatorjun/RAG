from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from enterprise_rag.domain.value_objects import Sha256Digest


@dataclass(frozen=True, slots=True)
class EvidenceItemDto:
    evidence_id: str
    chunk_id: str
    revision_id: str
    relative_path: str
    source_sha256: str
    ordinal: int
    start_char: int
    end_char: int
    content_sha256: str
    text: str

    def __post_init__(self) -> None:
        if not self.evidence_id.startswith("evidence:sha256:"):
            raise ValueError("invalid evidence ID")
        Sha256Digest(self.evidence_id.removeprefix("evidence:sha256:"))
        path = PurePosixPath(self.relative_path)
        if (
            not self.chunk_id
            or not self.revision_id
            or not self.relative_path
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("invalid evidence source")
        Sha256Digest(self.source_sha256)
        Sha256Digest(self.content_sha256)
        if self.ordinal < 0 or self.start_char < 0 or self.end_char <= self.start_char:
            raise ValueError("invalid evidence source span")
        if not self.text:
            raise ValueError("evidence text must not be empty")


@dataclass(frozen=True, slots=True)
class EvidenceBundleDto:
    items: tuple[EvidenceItemDto, ...]
    source_document_count: int
    source_structure_count: int

    def __post_init__(self) -> None:
        if self.source_document_count < 1 or self.source_structure_count < 1:
            raise ValueError("evidence source counts must be positive")
        if len(self.items) != self.source_structure_count:
            raise ValueError("every source structure must have one evidence item")
        evidence_ids = [item.evidence_id for item in self.items]
        chunk_ids = [item.chunk_id for item in self.items]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("duplicate evidence ID")
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("duplicate evidence chunk")
        paths = {item.relative_path for item in self.items}
        if len(paths) != self.source_document_count:
            raise ValueError("every source document must have evidence")
