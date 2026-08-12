from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_DOWNLOAD_ID = re.compile(r"^download-[0-9a-f]{32}$")
_MODEL_ID = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class ModelDownloadState(str, Enum):
    PREFLIGHT = "PREFLIGHT"
    DOWNLOADING = "DOWNLOADING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class ModelDownloadProgressDto:
    download_id: str
    model_id: str
    revision: str
    state: ModelDownloadState
    completed_bytes: int
    total_bytes: int
    completed_files: int
    total_files: int
    message: str

    def __post_init__(self) -> None:
        if _DOWNLOAD_ID.fullmatch(self.download_id) is None:
            raise ValueError("invalid model download ID")
        if _MODEL_ID.fullmatch(self.model_id) is None:
            raise ValueError("invalid Hugging Face model ID")
        if _COMMIT.fullmatch(self.revision) is None:
            raise ValueError("model revision must be an exact commit")
        if (
            self.completed_bytes < 0
            or self.total_bytes < 0
            or self.completed_bytes > self.total_bytes
        ):
            raise ValueError("invalid model download byte progress")
        if (
            self.completed_files < 0
            or self.total_files < 0
            or self.completed_files > self.total_files
        ):
            raise ValueError("invalid model download file progress")
        if not self.message:
            raise ValueError("model download progress message is required")

    @property
    def percentage(self) -> int:
        if self.total_bytes > 0:
            return min(100, self.completed_bytes * 100 // self.total_bytes)
        if self.total_files > 0:
            return min(100, self.completed_files * 100 // self.total_files)
        return 100 if self.state is ModelDownloadState.COMPLETED else 0
