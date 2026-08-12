from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_MODEL_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class DesktopSettingsDto:
    settings_revision: int
    source_root: str
    output_root: str
    model_id: str
    model_revision: str
    context_tokens: int
    max_output_tokens: int
    additional_system_prompt: str
    max_task_attempts: int
    offline_mode: bool
    notify_on_completion: bool

    def __post_init__(self) -> None:
        if self.settings_revision < 0:
            raise ValueError("desktop settings revision must be non-negative")
        source = self._absolute_path(self.source_root, "source root")
        output = self._absolute_path(self.output_root, "output root")
        if self._overlaps(source, output):
            raise ValueError("desktop source and output roots must not overlap")
        object.__setattr__(self, "source_root", str(source))
        object.__setattr__(self, "output_root", str(output))
        if not _MODEL_ID_PATTERN.fullmatch(self.model_id):
            raise ValueError("invalid Hugging Face model ID")
        if not _COMMIT_PATTERN.fullmatch(self.model_revision):
            raise ValueError("model revision must be a commit SHA")
        if (
            not 4_096 <= self.context_tokens <= 131_072
            or self.context_tokens % 1_024
        ):
            raise ValueError("invalid model context tokens")
        if not 512 <= self.max_output_tokens <= self.context_tokens - 512:
            raise ValueError("invalid maximum output tokens")
        if len(self.additional_system_prompt) > 20_000:
            raise ValueError("additional system prompt is too long")
        if not 1 <= self.max_task_attempts <= 3:
            raise ValueError("maximum task attempts must be between one and three")

    @staticmethod
    def _absolute_path(value: str, name: str) -> Path:
        path = Path(value).expanduser()
        if not value or not path.is_absolute():
            raise ValueError(f"desktop {name} must be absolute")
        return path.resolve(strict=False)

    @staticmethod
    def _overlaps(left: Path, right: Path) -> bool:
        try:
            left.relative_to(right)
            return True
        except ValueError:
            pass
        try:
            right.relative_to(left)
            return True
        except ValueError:
            return False
