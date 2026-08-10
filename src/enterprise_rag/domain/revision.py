# src/enterprise_rag/domain/revision.py
from enum import Enum


class RevisionRunState(str, Enum):
    PREPARED = "prepared"
    FINALIZED = "finalized"


class FileChangeStatus(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    UNCHANGED = "unchanged"
