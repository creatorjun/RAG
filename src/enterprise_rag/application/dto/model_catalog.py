from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_MODEL_ID = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class ModelCatalogOrigin(str, Enum):
    LOCAL_CACHE = "LOCAL_CACHE"
    HUGGING_FACE = "HUGGING_FACE"


class ModelCompatibility(str, Enum):
    SUPPORTED = "SUPPORTED"
    TIGHT = "TIGHT"
    TOO_LARGE = "TOO_LARGE"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ModelCatalogEntryDto:
    model_id: str
    revision: str
    origin: ModelCatalogOrigin
    cached: bool
    size_bytes: int | None
    quantization: str
    context_tokens: int | None
    license_name: str
    modified_at: str | None
    compatibility: ModelCompatibility
    compatibility_detail: str
    local_path: str | None = None
    gated: bool = False

    def __post_init__(self) -> None:
        if _MODEL_ID.fullmatch(self.model_id) is None:
            raise ValueError("invalid Hugging Face model ID")
        if _COMMIT.fullmatch(self.revision) is None:
            raise ValueError("model revision must be an exact commit")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("model size must be non-negative")
        if self.context_tokens is not None and self.context_tokens < 1:
            raise ValueError("model context must be positive")
        if not self.quantization or not self.license_name:
            raise ValueError("model metadata labels are required")
        if not self.compatibility_detail:
            raise ValueError("model compatibility detail is required")
        if self.cached != (self.local_path is not None):
            raise ValueError("model cache path is inconsistent")


@dataclass(frozen=True, slots=True)
class ModelCatalogDto:
    query: str
    remote: bool
    entries: tuple[ModelCatalogEntryDto, ...]

    def __post_init__(self) -> None:
        identities = [(entry.model_id, entry.revision) for entry in self.entries]
        if len(identities) != len(set(identities)):
            raise ValueError("model catalog entries must be unique")
