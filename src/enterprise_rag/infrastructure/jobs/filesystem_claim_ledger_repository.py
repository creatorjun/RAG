from __future__ import annotations

from typing import Any

from enterprise_rag.application.dto.claims import (
    ClaimDto,
    ClaimLedgerDto,
    ClaimRelationDto,
)
from enterprise_rag.application.ports.job_artifacts import JobArtifactRepositoryPort
from enterprise_rag.domain.claims import ClaimKind, ClaimRelationType
from enterprise_rag.domain.errors import revision_error

_LEDGER_PATH = "control/claim-ledger.json"


class FilesystemClaimLedgerRepository:
    def __init__(self, artifacts: JobArtifactRepositoryPort) -> None:
        self._artifacts = artifacts

    async def save(self, job_id: str, ledger: ClaimLedgerDto) -> str:
        return await self._artifacts.write_json_once(
            job_id,
            _LEDGER_PATH,
            {
                "schema_version": 1,
                "job_id": job_id,
                "reviewed_evidence_ids": list(ledger.reviewed_evidence_ids),
                "claims": [
                    {
                        "claim_id": claim.claim_id,
                        "kind": claim.kind.value,
                        "statement": claim.statement,
                        "evidence_ids": list(claim.evidence_ids),
                        "preconditions": list(claim.preconditions),
                        "commands": list(claim.commands),
                        "warnings": list(claim.warnings),
                    }
                    for claim in ledger.claims
                ],
                "relations": [
                    {
                        "left_claim_id": relation.left_claim_id,
                        "right_claim_id": relation.right_claim_id,
                        "relation": relation.relation.value,
                    }
                    for relation in ledger.relations
                ],
            },
        )

    async def load(self, job_id: str) -> ClaimLedgerDto:
        value = await self._artifacts.read_json(job_id, _LEDGER_PATH)
        try:
            if value.get("schema_version") != 1 or value.get("job_id") != job_id:
                raise ValueError("invalid claim ledger manifest")
            raw_claims = self._list(value["claims"])
            raw_relations = self._list(value["relations"])
            return ClaimLedgerDto(
                claims=tuple(self._claim(item) for item in raw_claims),
                relations=tuple(self._relation(item) for item in raw_relations),
                reviewed_evidence_ids=self._strings(value["reviewed_evidence_ids"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise revision_error("CLAIM_LEDGER_INVALID", {"job_id": job_id}) from error

    @staticmethod
    def _claim(value: Any) -> ClaimDto:
        item = FilesystemClaimLedgerRepository._mapping(value)
        return ClaimDto(
            claim_id=str(item["claim_id"]),
            kind=ClaimKind(str(item["kind"])),
            statement=str(item["statement"]),
            evidence_ids=FilesystemClaimLedgerRepository._strings(item["evidence_ids"]),
            preconditions=FilesystemClaimLedgerRepository._strings(item["preconditions"]),
            commands=FilesystemClaimLedgerRepository._strings(item["commands"]),
            warnings=FilesystemClaimLedgerRepository._strings(item["warnings"]),
        )

    @staticmethod
    def _relation(value: Any) -> ClaimRelationDto:
        item = FilesystemClaimLedgerRepository._mapping(value)
        return ClaimRelationDto(
            left_claim_id=str(item["left_claim_id"]),
            right_claim_id=str(item["right_claim_id"]),
            relation=ClaimRelationType(str(item["relation"])),
        )

    @staticmethod
    def _list(value: Any) -> list[Any]:
        if not isinstance(value, list):
            raise ValueError("expected list")
        return value

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("expected object")
        return value

    @staticmethod
    def _strings(value: Any) -> tuple[str, ...]:
        values = FilesystemClaimLedgerRepository._list(value)
        if any(not isinstance(item, str) for item in values):
            raise ValueError("expected strings")
        return tuple(values)
