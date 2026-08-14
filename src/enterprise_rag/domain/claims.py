from __future__ import annotations

from enum import Enum


class ClaimKind(str, Enum):
    FACT = "FACT"
    PROCEDURE = "PROCEDURE"
    COMMAND = "COMMAND"
    PREREQUISITE = "PREREQUISITE"
    WARNING = "WARNING"
    VALIDATION = "VALIDATION"
    ROLLBACK = "ROLLBACK"


class ClaimRelationType(str, Enum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    SEMANTIC_EQUIVALENT = "SEMANTIC_EQUIVALENT"
    COMPLEMENTARY = "COMPLEMENTARY"
    CONTEXTUAL_REPEAT = "CONTEXTUAL_REPEAT"
    CONFLICT = "CONFLICT"
    UNRELATED = "UNRELATED"


_RELATION_MERGE_PRIORITY = {
    ClaimRelationType.CONFLICT: 0,
    ClaimRelationType.COMPLEMENTARY: 1,
    ClaimRelationType.CONTEXTUAL_REPEAT: 2,
    ClaimRelationType.SEMANTIC_EQUIVALENT: 3,
    ClaimRelationType.EXACT_DUPLICATE: 4,
    ClaimRelationType.UNRELATED: 5,
}


def claim_relation_merge_priority(relation: ClaimRelationType) -> int:
    """Rank relation labels from the most conservative to the least informative."""

    return _RELATION_MERGE_PRIORITY[relation]
