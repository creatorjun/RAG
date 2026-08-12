from __future__ import annotations

from dataclasses import dataclass

from enterprise_rag.domain.claims import ClaimKind, ClaimRelationType
from enterprise_rag.domain.value_objects import Sha256Digest


def _validate_texts(values: tuple[str, ...], name: str) -> None:
    if len(values) != len(set(values)) or any(not value.strip() for value in values):
        raise ValueError(f"invalid claim {name}")


def _validate_evidence_ids(values: tuple[str, ...]) -> None:
    if not values or len(values) != len(set(values)):
        raise ValueError("claim evidence IDs must be non-empty and unique")
    for value in values:
        if not value.startswith("evidence:sha256:"):
            raise ValueError("invalid claim evidence ID")
        Sha256Digest(value.removeprefix("evidence:sha256:"))


@dataclass(frozen=True, slots=True)
class ClaimDraftDto:
    draft_id: str
    kind: ClaimKind
    statement: str
    evidence_ids: tuple[str, ...]
    preconditions: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.draft_id or len(self.draft_id) > 128:
            raise ValueError("invalid claim draft ID")
        if not self.statement.strip() or len(self.statement) > 20_000:
            raise ValueError("invalid claim statement")
        _validate_evidence_ids(self.evidence_ids)
        _validate_texts(self.preconditions, "preconditions")
        _validate_texts(self.commands, "commands")
        _validate_texts(self.warnings, "warnings")


@dataclass(frozen=True, slots=True)
class ClaimDto:
    claim_id: str
    kind: ClaimKind
    statement: str
    evidence_ids: tuple[str, ...]
    preconditions: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.claim_id.startswith("claim:sha256:"):
            raise ValueError("invalid claim ID")
        Sha256Digest(self.claim_id.removeprefix("claim:sha256:"))
        if not self.statement.strip():
            raise ValueError("invalid claim statement")
        _validate_evidence_ids(self.evidence_ids)
        _validate_texts(self.preconditions, "preconditions")
        _validate_texts(self.commands, "commands")
        _validate_texts(self.warnings, "warnings")


@dataclass(frozen=True, slots=True)
class ClaimRelationDraftDto:
    left_draft_id: str
    right_draft_id: str
    relation: ClaimRelationType

    def __post_init__(self) -> None:
        if not self.left_draft_id or not self.right_draft_id:
            raise ValueError("claim relation draft IDs are required")
        if self.left_draft_id == self.right_draft_id:
            raise ValueError("claim relation cannot reference itself")


@dataclass(frozen=True, slots=True)
class ClaimRelationDto:
    left_claim_id: str
    right_claim_id: str
    relation: ClaimRelationType

    def __post_init__(self) -> None:
        if self.left_claim_id >= self.right_claim_id:
            raise ValueError("claim relation IDs must be canonical and distinct")


@dataclass(frozen=True, slots=True)
class ClaimLedgerDto:
    claims: tuple[ClaimDto, ...]
    relations: tuple[ClaimRelationDto, ...]
    reviewed_evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.claims:
            raise ValueError("claim ledger must contain claims")
        _validate_evidence_ids(self.reviewed_evidence_ids)
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("duplicate claim ID")
        known_evidence = set(self.reviewed_evidence_ids)
        if any(not set(claim.evidence_ids).issubset(known_evidence) for claim in self.claims):
            raise ValueError("claim references unknown evidence")
        known_claims = set(claim_ids)
        pairs: set[tuple[str, str]] = set()
        for relation in self.relations:
            if {
                relation.left_claim_id,
                relation.right_claim_id,
            } - known_claims:
                raise ValueError("relation references unknown claim")
            pair = (relation.left_claim_id, relation.right_claim_id)
            if pair in pairs:
                raise ValueError("duplicate claim relation")
            pairs.add(pair)
