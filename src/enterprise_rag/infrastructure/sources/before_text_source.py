# src/enterprise_rag/infrastructure/sources/before_text_source.py
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path, PurePosixPath

from enterprise_rag.application.dto.long_document import TextDocumentDto
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.infrastructure.workspace.path_security import (
    is_link_or_reparse,
    is_within,
    resolve_existing_root,
)

_TEXT_EXTENSIONS = {
    ".csv",
    ".html",
    ".ini",
    ".json",
    ".md",
    ".rst",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


class BeforeTextDocumentSource:
    def __init__(self, before_root: Path, maximum_file_bytes: int) -> None:
        self._before_root = resolve_existing_root(before_root, before=True)
        self._maximum_file_bytes = maximum_file_bytes

    async def read(self, relative_path: str) -> TextDocumentDto:
        try:
            return await asyncio.to_thread(self._read, relative_path)
        except ApplicationError:
            raise
        except OSError as error:
            raise revision_error("IO_FAILURE", {"relative_path": relative_path}) from error

    def _read(self, relative_path: str) -> TextDocumentDto:
        relative = self._validate_relative_path(relative_path)
        candidate = self._before_root.joinpath(*relative.parts)
        current = self._before_root
        for part in relative.parts:
            current = current / part
            if is_link_or_reparse(current):
                raise revision_error("LINK_NOT_ALLOWED", {"relative_path": relative_path})
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as error:
            raise revision_error(
                "BEFORE_ROOT_NOT_READABLE", {"relative_path": relative_path}
            ) from error
        if not is_within(resolved, self._before_root):
            raise revision_error("PATH_ESCAPE", {"relative_path": relative_path})
        if not resolved.is_file():
            raise revision_error("TEXT_FORMAT_UNSUPPORTED", {"relative_path": relative_path})
        if resolved.suffix.lower() not in _TEXT_EXTENSIONS:
            raise revision_error("TEXT_FORMAT_UNSUPPORTED", {"relative_path": relative_path})
        before = resolved.stat()
        if before.st_size > self._maximum_file_bytes:
            raise revision_error(
                "DOCUMENT_TOO_LARGE",
                {"byte_count": before.st_size, "maximum_file_bytes": self._maximum_file_bytes},
            )
        content = resolved.read_bytes()
        after = resolved.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            raise revision_error("SOURCE_BUSY", {"relative_path": relative_path})
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise revision_error(
                "TEXT_FORMAT_UNSUPPORTED", {"relative_path": relative_path}
            ) from error
        source_sha256 = hashlib.sha256(content).hexdigest()
        identity = f"{relative.as_posix()}\0{source_sha256}"
        revision_id = f"sha256:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"
        return TextDocumentDto(revision_id, relative.as_posix(), source_sha256, text)

    @staticmethod
    def _validate_relative_path(relative_path: str) -> PurePosixPath:
        if not relative_path or "\\" in relative_path or "\x00" in relative_path:
            raise revision_error("PATH_ESCAPE")
        path = PurePosixPath(relative_path)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise revision_error("PATH_ESCAPE", {"relative_path": relative_path})
        return path
