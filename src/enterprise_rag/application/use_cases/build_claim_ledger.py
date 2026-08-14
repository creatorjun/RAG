from __future__ import annotations

import hashlib
import json
import re

from enterprise_rag.application.dto.claims import (
    ClaimDraftDto,
    ClaimDto,
    ClaimLedgerDto,
    ClaimRelationDraftDto,
    ClaimRelationDto,
)
from enterprise_rag.application.dto.evidence import EvidenceBundleDto
from enterprise_rag.domain.claims import ClaimRelationType
from enterprise_rag.domain.errors import revision_error

_PROTECTED_TERM = re.compile(
    r"(?i)(?:(?<![0-9A-Za-z])\d+(?:\.\d+)*(?![0-9A-Za-z])|"
    r"\b(?:not|never|unsupported|required)\b|"
    r"금지|아니|않|불가|제외|미지원|필수)"
)


class BuildClaimLedger:
    def execute(
        self,
        evidence: EvidenceBundleDto,
        drafts: tuple[ClaimDraftDto, ...],
        relation_drafts: tuple[ClaimRelationDraftDto, ...] = (),
    ) -> ClaimLedgerDto:
        if not drafts:
            raise revision_error("CLAIM_LEDGER_INVALID")
        known_evidence = {item.evidence_id for item in evidence.items}
        draft_ids = [draft.draft_id for draft in drafts]
        if len(draft_ids) != len(set(draft_ids)):
            raise revision_error("CLAIM_LEDGER_INVALID")
        draft_by_id = {draft.draft_id: draft for draft in drafts}

        drafts_by_key: dict[str, list[ClaimDraftDto]] = {}
        for claim_draft in drafts:
            if not set(claim_draft.evidence_ids).issubset(known_evidence):
                raise revision_error("CLAIM_LEDGER_INVALID")
            drafts_by_key.setdefault(self._content_key(claim_draft), []).append(claim_draft)

        parent = {draft.draft_id: draft.draft_id for draft in drafts}

        def find(draft_id: str) -> str:
            while parent[draft_id] != draft_id:
                parent[draft_id] = parent[parent[draft_id]]
                draft_id = parent[draft_id]
            return draft_id

        def union(left: str, right: str) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root == right_root:
                return
            parent[max(left_root, right_root)] = min(left_root, right_root)

        for grouped_drafts in drafts_by_key.values():
            for duplicate in grouped_drafts[1:]:
                union(grouped_drafts[0].draft_id, duplicate.draft_id)

        for relation in relation_drafts:
            left_draft = draft_by_id.get(relation.left_draft_id)
            right_draft = draft_by_id.get(relation.right_draft_id)
            if left_draft is None or right_draft is None:
                raise revision_error("CLAIM_LEDGER_INVALID")
            if self._safe_to_collapse(left_draft, right_draft, relation.relation):
                union(left_draft.draft_id, right_draft.draft_id)

        grouped_by_root: dict[str, list[ClaimDraftDto]] = {}
        for draft in drafts:
            grouped_by_root.setdefault(find(draft.draft_id), []).append(draft)

        claims_by_id: dict[str, ClaimDto] = {}
        claim_by_draft: dict[str, str] = {}
        for grouped_drafts in grouped_by_root.values():
            representative = self._representative(grouped_drafts)
            evidence_ids = tuple(
                sorted(
                    {
                        evidence_id
                        for claim_draft in grouped_drafts
                        for evidence_id in claim_draft.evidence_ids
                    }
                )
            )
            claim = self._claim(representative, evidence_ids)
            claims_by_id[claim.claim_id] = claim
            for claim_draft in grouped_drafts:
                claim_by_draft[claim_draft.draft_id] = claim.claim_id

        relations_by_pair: dict[tuple[str, str], ClaimRelationDto] = {}
        for relation_draft in relation_drafts:
            left_claim = claim_by_draft.get(relation_draft.left_draft_id)
            right_claim = claim_by_draft.get(relation_draft.right_draft_id)
            if left_claim is None or right_claim is None:
                raise revision_error("CLAIM_LEDGER_INVALID")
            if left_claim == right_claim:
                if relation_draft.relation in {
                    ClaimRelationType.EXACT_DUPLICATE,
                    ClaimRelationType.SEMANTIC_EQUIVALENT,
                }:
                    continue
                raise revision_error("CLAIM_LEDGER_INVALID")
            left_claim, right_claim = sorted((left_claim, right_claim))
            claim_relation = ClaimRelationDto(
                left_claim,
                right_claim,
                relation_draft.relation,
            )
            existing = relations_by_pair.get((left_claim, right_claim))
            if existing is not None and existing.relation is not claim_relation.relation:
                raise revision_error("CLAIM_LEDGER_INVALID")
            relations_by_pair[(left_claim, right_claim)] = claim_relation
        try:
            reviewed_evidence = {
                evidence_id for claim in claims_by_id.values() for evidence_id in claim.evidence_ids
            }
            return ClaimLedgerDto(
                claims=tuple(sorted(claims_by_id.values(), key=lambda item: item.claim_id)),
                relations=tuple(
                    sorted(
                        relations_by_pair.values(),
                        key=lambda item: (item.left_claim_id, item.right_claim_id),
                    )
                ),
                reviewed_evidence_ids=tuple(sorted(reviewed_evidence)),
            )
        except ValueError as error:
            raise revision_error("CLAIM_LEDGER_INVALID") from error

    @staticmethod
    def _content_key(draft: ClaimDraftDto) -> str:
        payload = {
            "kind": draft.kind.value,
            "statement": draft.statement.strip(),
            "preconditions": list(draft.preconditions),
            "commands": list(draft.commands),
            "warnings": list(draft.warnings),
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def _safe_to_collapse(
        cls,
        left: ClaimDraftDto,
        right: ClaimDraftDto,
        relation: ClaimRelationType,
    ) -> bool:
        if relation not in {
            ClaimRelationType.EXACT_DUPLICATE,
            ClaimRelationType.SEMANTIC_EQUIVALENT,
        }:
            return False
        metadata_matches = (
            left.kind is right.kind
            and left.preconditions == right.preconditions
            and left.commands == right.commands
            and left.warnings == right.warnings
        )
        if not metadata_matches:
            return False
        if relation is ClaimRelationType.EXACT_DUPLICATE:
            return cls._normalized_statement(left.statement) == cls._normalized_statement(
                right.statement
            )
        if cls._protected_terms(left.statement) != cls._protected_terms(right.statement):
            return False
        has_shared_safety_metadata = bool(left.preconditions or left.commands or left.warnings)
        return (
            has_shared_safety_metadata
            or cls._statement_similarity(left.statement, right.statement) >= 0.3
        )

    @staticmethod
    def _normalized_statement(value: str) -> str:
        return "".join(character for character in value.casefold() if character.isalnum())

    @staticmethod
    def _protected_terms(value: str) -> tuple[str, ...]:
        return tuple(sorted(match.casefold() for match in _PROTECTED_TERM.findall(value)))

    @classmethod
    def _statement_similarity(cls, left: str, right: str) -> float:
        def shingles(value: str) -> set[str]:
            normalized = cls._normalized_statement(value)
            return {
                normalized[index : index + 3]
                for index in range(max(1, len(normalized) - 2))
                if normalized[index : index + 3]
            }

        left_shingles = shingles(left)
        right_shingles = shingles(right)
        union = left_shingles | right_shingles
        return len(left_shingles & right_shingles) / len(union) if union else 1.0

    @classmethod
    def _representative(
        cls,
        drafts: list[ClaimDraftDto],
    ) -> ClaimDraftDto:
        return min(
            drafts,
            key=lambda draft: (
                -len(draft.statement.strip()),
                cls._content_key(draft),
                draft.draft_id,
            ),
        )

    @staticmethod
    def _claim(draft: ClaimDraftDto, evidence_ids: tuple[str, ...]) -> ClaimDto:
        payload = {
            "kind": draft.kind.value,
            "statement": draft.statement.strip(),
            "evidence_ids": list(evidence_ids),
            "preconditions": list(draft.preconditions),
            "commands": list(draft.commands),
            "warnings": list(draft.warnings),
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        claim_id = "claim:sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return ClaimDto(
            claim_id=claim_id,
            kind=draft.kind,
            statement=draft.statement.strip(),
            evidence_ids=evidence_ids,
            preconditions=draft.preconditions,
            commands=draft.commands,
            warnings=draft.warnings,
        )
