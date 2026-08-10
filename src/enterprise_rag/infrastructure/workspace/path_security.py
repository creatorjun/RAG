# src/enterprise_rag/infrastructure/workspace/path_security.py
from __future__ import annotations

import stat
from pathlib import Path

from enterprise_rag.domain.errors import revision_error


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def is_link_or_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def resolve_existing_root(path: Path, before: bool) -> Path:
    if is_link_or_reparse(path):
        raise revision_error("LINK_NOT_ALLOWED")
    try:
        resolved = path.expanduser().resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError, PermissionError) as error:
        code = "BEFORE_ROOT_NOT_READABLE" if before else "IO_FAILURE"
        raise revision_error(code) from error
    if path.expanduser().absolute() != resolved:
        raise revision_error("LINK_NOT_ALLOWED")
    if not resolved.is_dir():
        code = "BEFORE_ROOT_NOT_READABLE" if before else "IO_FAILURE"
        raise revision_error(code)
    return resolved


def validate_non_overlapping(before_root: Path, after_root: Path) -> None:
    if (
        before_root == after_root
        or is_within(before_root, after_root)
        or is_within(after_root, before_root)
    ):
        raise revision_error("BEFORE_AFTER_OVERLAP")


def validate_tree(root: Path) -> None:
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if is_link_or_reparse(path):
            raise revision_error("LINK_NOT_ALLOWED", {"relative_path": relative})
        try:
            resolved = path.resolve(strict=True)
        except (FileNotFoundError, PermissionError) as error:
            raise revision_error("IO_FAILURE", {"relative_path": relative}) from error
        if not is_within(resolved, root):
            raise revision_error("PATH_ESCAPE", {"relative_path": relative})
        if not path.is_dir() and not path.is_file():
            raise revision_error("PATH_ESCAPE", {"relative_path": relative})
