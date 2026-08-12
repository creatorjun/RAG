from __future__ import annotations

import asyncio
import unittest

from enterprise_rag.application.dto.claims import ClaimDraftDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto, EvidenceItemDto
from enterprise_rag.application.use_cases.extract_claim_drafts import ExtractClaimDrafts
from enterprise_rag.domain.claims import ClaimKind
from enterprise_rag.domain.errors import ApplicationError


def _evidence(identifier: str, path: str) -> EvidenceItemDto:
    return EvidenceItemDto(
        "evidence:sha256:" + identifier * 64,
        f"chunk:{identifier}",
        f"revision:{identifier}",
        path,
        "c" * 64,
        0,
        0,
        4,
        "d" * 64,
        "text",
    )


class _Generator:
    def __init__(self, wrong_evidence: bool = False) -> None:
        self.wrong_evidence = wrong_evidence

    async def generate(self, evidence, instruction):
        evidence_id = (
            "evidence:sha256:" + "f" * 64
            if self.wrong_evidence
            else evidence.evidence_id
        )
        return (
            ClaimDraftDto(
                f"draft:{evidence.chunk_id}",
                ClaimKind.FACT,
                "사실",
                (evidence_id,),
            ),
        )


class ExtractClaimDraftsTest(unittest.TestCase):
    def test_extracts_every_evidence_item_with_count_progress(self) -> None:
        evidence = EvidenceBundleDto(
            (_evidence("a", "one.md"), _evidence("b", "two.md")),
            2,
            2,
        )
        progress = []
        drafts = asyncio.run(
            ExtractClaimDrafts(_Generator()).execute(
                evidence,
                "통합 문서 작성",
                lambda completed, total, evidence_id: progress.append(
                    (completed, total, evidence_id)
                ),
            )
        )
        self.assertEqual(len(drafts), 2)
        self.assertEqual(progress[-1][:2], (2, 2))

    def test_rejects_claim_that_references_another_evidence_item(self) -> None:
        evidence = EvidenceBundleDto((_evidence("a", "one.md"),), 1, 1)
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(
                ExtractClaimDrafts(_Generator(wrong_evidence=True)).execute(
                    evidence,
                    "통합 문서 작성",
                )
            )
        self.assertEqual(captured.exception.code, "CLAIM_LEDGER_INVALID")


if __name__ == "__main__":
    unittest.main()
