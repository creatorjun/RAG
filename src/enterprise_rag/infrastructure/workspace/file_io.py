# src/enterprise_rag/infrastructure/workspace/file_io.py
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, value: Any) -> None:
    serialized = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, serialized)
