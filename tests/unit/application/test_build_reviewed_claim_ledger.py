from __future__ import annotations

import asyncio
import unittest

from enterprise_rag.application.dto.claims import (
    ClaimDraftDto,
    ClaimRelationDraftDto,
)
from enterprise_rag.application.dto.evidence import EvidenceBundleDto, EvidenceItemDto
from enterprise_rag.application.use_cases.build_claim_ledger import BuildClaimLedger
from enterprise_rag.application.use_cases.build_reviewed_claim_ledger import (
    BuildReviewedClaimLedger,
)
from enterprise_rag.domain.claims import ClaimKind, ClaimRelationType


class _Relations:
    async def generate(self, drafts, evidence, instruction):
        return (
            ClaimRelationDraftDto(
                drafts[0].draft_id,
                drafts[1].draft_id,
                ClaimRelationType.COMPLEMENTARY,
            ),
        )


class BuildReviewedClaimLedgerTest(unittest.TestCase):
    def test_combines_model_relation_proposal_with_deterministic_ledger(self) -> None:
        evidence_id = "evidence:sha256:" + "a" * 64
        evidence = EvidenceBundleDto(
            (
                EvidenceItemDto(
                    evidence_id,
                    "chunk:1",
                    "revision:1",
                    "guide.md",
                    "b" * 64,
                    0,
                    0,
                    4,
                    "c" * 64,
                    "text",
                ),
            ),
            1,
            1,
        )
        drafts = (
            ClaimDraftDto(
                "draft:one",
                ClaimKind.PROCEDURE,
                "서비스를 시작한다.",
                (evidence_id,),
            ),
            ClaimDraftDto(
                "draft:two",
                ClaimKind.VALIDATION,
                "서비스 상태를 확인한다.",
                (evidence_id,),
            ),
        )
        ledger = asyncio.run(
            BuildReviewedClaimLedger(_Relations(), BuildClaimLedger()).execute(
                evidence,
                drafts,
                "서비스 운영 문서",
            )
        )
        self.assertEqual(len(ledger.relations), 1)
        self.assertEqual(
            ledger.relations[0].relation,
            ClaimRelationType.COMPLEMENTARY,
        )


if __name__ == "__main__":
    unittest.main()
