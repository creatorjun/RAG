from __future__ import annotations

import hashlib
import json

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

        drafts_by_key: dict[str, list[ClaimDraftDto]] = {}
        for claim_draft in drafts:
            if not set(claim_draft.evidence_ids).issubset(known_evidence):
                raise revision_error("CLAIM_LEDGER_INVALID")
            drafts_by_key.setdefault(self._content_key(claim_draft), []).append(
                claim_draft
            )

        claims_by_id: dict[str, ClaimDto] = {}
        claim_by_draft: dict[str, str] = {}
        for grouped_drafts in drafts_by_key.values():
            representative = grouped_drafts[0]
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
            left = claim_by_draft.get(relation_draft.left_draft_id)
            right = claim_by_draft.get(relation_draft.right_draft_id)
            if left is None or right is None:
                raise revision_error("CLAIM_LEDGER_INVALID")
            if left == right:
                if relation_draft.relation is ClaimRelationType.EXACT_DUPLICATE:
                    continue
                raise revision_error("CLAIM_LEDGER_INVALID")
            left, right = sorted((left, right))
            relation = ClaimRelationDto(left, right, relation_draft.relation)
            existing = relations_by_pair.get((left, right))
            if existing is not None and existing.relation is not relation.relation:
                raise revision_error("CLAIM_LEDGER_INVALID")
            relations_by_pair[(left, right)] = relation
        try:
            return ClaimLedgerDto(
                claims=tuple(sorted(claims_by_id.values(), key=lambda item: item.claim_id)),
                relations=tuple(
                    sorted(
                        relations_by_pair.values(),
                        key=lambda item: (item.left_claim_id, item.right_claim_id),
                    )
                ),
                reviewed_evidence_ids=tuple(sorted(known_evidence)),
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
