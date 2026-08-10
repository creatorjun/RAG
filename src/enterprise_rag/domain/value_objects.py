# src/enterprise_rag/domain/value_objects.py
from __future__ import annotations

import re
from dataclasses import dataclass

_RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}[a-z0-9]$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RunId:
    value: str

    def __post_init__(self) -> None:
        if not _RUN_ID_PATTERN.fullmatch(self.value):
            raise ValueError("invalid run ID")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Sha256Digest:
    value: str

    def __post_init__(self) -> None:
        if not _SHA256_PATTERN.fullmatch(self.value):
            raise ValueError("invalid SHA-256 digest")

    def __str__(self) -> str:
        return self.value
