from __future__ import annotations

import re
from typing import Any

from enterprise_rag.application.dto.claims import ClaimDraftDto
from enterprise_rag.application.ports.job_artifacts import JobArtifactRepositoryPort
from enterprise_rag.domain.claims import ClaimKind
from enterprise_rag.domain.errors import ApplicationError, revision_error


class FilesystemClaimDraftRepository:
    def __init__(self, artifacts: JobArtifactRepositoryPort) -> None:
        self._artifacts = artifacts

    async def save(
        self,
        job_id: str,
        evidence_id: str,
        drafts: tuple[ClaimDraftDto, ...],
    ) -> str:
        if any(draft.evidence_ids != (evidence_id,) for draft in drafts):
            raise revision_error("CLAIM_LEDGER_INVALID", {"evidence_id": evidence_id})
        return await self._artifacts.write_json_once(
            job_id,
            self._path(evidence_id),
            {
                "schema_version": 1,
                "job_id": job_id,
                "evidence_id": evidence_id,
                "drafts": [
                    {
                        "draft_id": draft.draft_id,
                        "kind": draft.kind.value,
                        "statement": draft.statement,
                        "evidence_ids": list(draft.evidence_ids),
                        "preconditions": list(draft.preconditions),
                        "commands": list(draft.commands),
                        "warnings": list(draft.warnings),
                    }
                    for draft in drafts
                ],
            },
        )

    async def load(
        self,
        job_id: str,
        evidence_id: str,
    ) -> tuple[ClaimDraftDto, ...] | None:
        try:
            value = await self._artifacts.read_json(job_id, self._path(evidence_id))
        except ApplicationError as error:
            if error.code == "JOB_ARTIFACT_NOT_FOUND":
                return None
            raise
        try:
            if (
                value.get("schema_version") != 1
                or value.get("job_id") != job_id
                or value.get("evidence_id") != evidence_id
            ):
                raise ValueError("claim draft checkpoint identity is invalid")
            raw_drafts = value["drafts"]
            if not isinstance(raw_drafts, list):
                raise ValueError("claim draft checkpoint is invalid")
            drafts = tuple(self._draft(item) for item in raw_drafts)
            if any(draft.evidence_ids != (evidence_id,) for draft in drafts):
                raise ValueError("claim draft evidence is invalid")
            return drafts
        except (KeyError, TypeError, ValueError) as error:
            raise revision_error(
                "CLAIM_LEDGER_INVALID",
                {"evidence_id": evidence_id},
            ) from error

    @staticmethod
    def _path(evidence_id: str) -> str:
        prefix = "evidence:sha256:"
        digest = evidence_id.removeprefix(prefix)
        if (
            not evidence_id.startswith(prefix)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise revision_error("CLAIM_LEDGER_INVALID", {"evidence_id": evidence_id})
        return f"claim-drafts/{digest}.json"

    @staticmethod
    def _draft(value: Any) -> ClaimDraftDto:
        if not isinstance(value, dict):
            raise ValueError("claim draft item is invalid")

        def strings(raw: Any) -> tuple[str, ...]:
            if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
                raise ValueError("claim draft strings are invalid")
            return tuple(raw)

        return ClaimDraftDto(
            draft_id=str(value["draft_id"]),
            kind=ClaimKind(str(value["kind"])),
            statement=str(value["statement"]),
            evidence_ids=strings(value["evidence_ids"]),
            preconditions=strings(value["preconditions"]),
            commands=strings(value["commands"]),
            warnings=strings(value["warnings"]),
        )
