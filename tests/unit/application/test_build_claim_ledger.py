from __future__ import annotations

import unittest

from enterprise_rag.application.dto.claims import ClaimDraftDto, ClaimRelationDraftDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto, EvidenceItemDto
from enterprise_rag.application.use_cases.build_claim_ledger import BuildClaimLedger
from enterprise_rag.domain.claims import ClaimKind, ClaimRelationType
from enterprise_rag.domain.errors import ApplicationError


def _evidence(identifier: str = "a") -> EvidenceItemDto:
    return EvidenceItemDto(
        evidence_id="evidence:sha256:" + identifier * 64,
        chunk_id=f"chunk:{identifier}",
        revision_id="revision:1",
        relative_path="guide.md",
        source_sha256="b" * 64,
        ordinal=0,
        start_char=0,
        end_char=4,
        content_sha256="c" * 64,
        text="text",
    )


class BuildClaimLedgerTest(unittest.TestCase):
    def test_builds_deterministic_claims_and_canonical_relations(self) -> None:
        evidence = EvidenceBundleDto((_evidence(),), 1, 1)
        first = ClaimDraftDto(
            "draft:1",
            ClaimKind.PROCEDURE,
            "서비스를 시작한다.",
            (evidence.items[0].evidence_id,),
            commands=("systemctl start example",),
        )
        second = ClaimDraftDto(
            "draft:2",
            ClaimKind.VALIDATION,
            "서비스 상태를 확인한다.",
            (evidence.items[0].evidence_id,),
            commands=("systemctl is-active example",),
        )
        relation = ClaimRelationDraftDto(
            "draft:2",
            "draft:1",
            ClaimRelationType.COMPLEMENTARY,
        )
        builder = BuildClaimLedger()
        ledger = builder.execute(evidence, (first, second), (relation,))
        repeated = builder.execute(evidence, (first, second), (relation,))
        self.assertEqual(ledger, repeated)
        self.assertEqual(len(ledger.claims), 2)
        self.assertEqual(len(ledger.relations), 1)
        self.assertLess(
            ledger.relations[0].left_claim_id,
            ledger.relations[0].right_claim_id,
        )

    def test_collapses_identical_drafts_and_ignores_exact_self_relation(self) -> None:
        evidence = EvidenceBundleDto((_evidence(),), 1, 1)
        first = ClaimDraftDto(
            "draft:1",
            ClaimKind.FACT,
            "SELinux는 Enforcing이다.",
            (evidence.items[0].evidence_id,),
        )
        second = ClaimDraftDto(
            "draft:2",
            first.kind,
            first.statement,
            first.evidence_ids,
        )
        relation = ClaimRelationDraftDto(
            "draft:1",
            "draft:2",
            ClaimRelationType.EXACT_DUPLICATE,
        )
        ledger = BuildClaimLedger().execute(evidence, (first, second), (relation,))
        self.assertEqual(len(ledger.claims), 1)
        self.assertEqual(ledger.relations, ())

    def test_merges_identical_claim_content_across_distinct_evidence(self) -> None:
        first_evidence = _evidence("a")
        second_evidence = _evidence("d")
        evidence = EvidenceBundleDto((first_evidence, second_evidence), 1, 2)
        first = ClaimDraftDto(
            "draft:1",
            ClaimKind.WARNING,
            "운영 시간에 재시작하지 않는다.",
            (first_evidence.evidence_id,),
        )
        second = ClaimDraftDto(
            "draft:2",
            first.kind,
            first.statement,
            (second_evidence.evidence_id,),
        )
        ledger = BuildClaimLedger().execute(evidence, (first, second))
        self.assertEqual(len(ledger.claims), 1)
        self.assertEqual(
            ledger.claims[0].evidence_ids,
            tuple(sorted((first_evidence.evidence_id, second_evidence.evidence_id))),
        )

    def test_excludes_evidence_without_technical_claims_from_reviewed_coverage(self) -> None:
        technical = _evidence("a")
        irrelevant = _evidence("d")
        evidence = EvidenceBundleDto((technical, irrelevant), 1, 2)
        draft = ClaimDraftDto(
            "draft:1",
            ClaimKind.FACT,
            "SELinux는 Enforcing이다.",
            (technical.evidence_id,),
        )

        ledger = BuildClaimLedger().execute(evidence, (draft,))

        self.assertEqual(ledger.reviewed_evidence_ids, (technical.evidence_id,))

    def test_rejects_unknown_evidence_and_conflicting_relation_labels(self) -> None:
        evidence = EvidenceBundleDto((_evidence(),), 1, 1)
        unknown = ClaimDraftDto(
            "draft:unknown",
            ClaimKind.FACT,
            "근거 없음",
            ("evidence:sha256:" + "f" * 64,),
        )
        with self.assertRaises(ApplicationError) as captured:
            BuildClaimLedger().execute(evidence, (unknown,))
        self.assertEqual(captured.exception.code, "CLAIM_LEDGER_INVALID")

        one = ClaimDraftDto(
            "draft:1", ClaimKind.FACT, "one", (evidence.items[0].evidence_id,)
        )
        two = ClaimDraftDto(
            "draft:2", ClaimKind.FACT, "two", (evidence.items[0].evidence_id,)
        )
        relations = (
            ClaimRelationDraftDto(
                "draft:1", "draft:2", ClaimRelationType.COMPLEMENTARY
            ),
            ClaimRelationDraftDto("draft:1", "draft:2", ClaimRelationType.CONFLICT),
        )
        with self.assertRaises(ApplicationError) as captured:
            BuildClaimLedger().execute(evidence, (one, two), relations)
        self.assertEqual(captured.exception.code, "CLAIM_LEDGER_INVALID")


if __name__ == "__main__":
    unittest.main()
