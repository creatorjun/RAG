from __future__ import annotations

import re
from pathlib import PurePosixPath

from enterprise_rag.application.dto.claims import ClaimDto, ClaimLedgerDto
from enterprise_rag.application.dto.evidence import EvidenceBundleDto
from enterprise_rag.application.dto.tasks import TaskOutputDto, TaskPlanDto

_SOURCE_CITATION = re.compile(r"\[source:([^\]\r\n]+)\]")
_INTERNAL_REFERENCE = re.compile(r"\[(?:claim|evidence):[^\]\r\n]+\]")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_TAG_TOKEN = re.compile(r"[0-9A-Za-z가-힣][0-9A-Za-z가-힣._+-]{1,31}")


class ObserveDocument:
    """Create retrieval metadata and non-blocking quality observations."""

    def execute(
        self,
        markdown: str,
        plan: TaskPlanDto,
        ledger: ClaimLedgerDto,
        evidence: EvidenceBundleDto,
        outputs: tuple[TaskOutputDto, ...],
    ) -> dict[str, object]:
        claim_by_id = {claim.claim_id: claim for claim in ledger.claims}
        evidence_by_id = {item.evidence_id: item for item in evidence.items}
        output_by_task = {output.task_id: output for output in outputs}
        retrieval_units: list[dict[str, object]] = []
        for task in plan.tasks:
            claims = [claim_by_id[claim_id] for claim_id in task.owned_claim_ids]
            source_paths = sorted(
                {
                    evidence_by_id[evidence_id].relative_path
                    for claim in claims
                    for evidence_id in claim.evidence_ids
                }
            )
            output = output_by_task.get(task.task_id)
            headings = [section.heading for section in output.sections] if output else []
            tags = self._tags(task.title, claims, source_paths)
            queries = self._ordered_unique(
                [task.title.strip(), task.objective.strip()]
                + [claim.statement.strip() for claim in claims]
            )[:10]
            retrieval_units.append(
                {
                    "unit_id": task.task_id,
                    "title": task.title,
                    "parent_title": markdown.splitlines()[0].removeprefix("# ").strip(),
                    "section_headings": headings,
                    "claim_kinds": sorted({claim.kind.value for claim in claims}),
                    "tags": tags,
                    "expected_queries": queries,
                    "source_paths": source_paths,
                }
            )

        duplicate_count = self._duplicate_prose_count(markdown)
        heading_anomalies = sum(
            1 for _, heading in _HEADING.findall(markdown) if heading.lstrip().startswith("#")
        )
        return {
            "schema_version": 1,
            "mode": "NON_BLOCKING_OBSERVATION",
            "metrics": {
                "character_count": len(markdown),
                "word_count": len(markdown.split()),
                "heading_count": len(_HEADING.findall(markdown)),
                "heading_anomaly_count": heading_anomalies,
                "source_citation_count": len(_SOURCE_CITATION.findall(markdown)),
                "unique_source_count": len(set(_SOURCE_CITATION.findall(markdown))),
                "internal_reference_count": len(_INTERNAL_REFERENCE.findall(markdown)),
                "duplicate_prose_block_count": duplicate_count,
            },
            "canonical_claim_owners": {
                entry.claim_id: entry.owner_task_id for entry in plan.coverage.claim_coverage
            },
            "retrieval_units": retrieval_units,
        }

    @classmethod
    def _tags(cls, title: str, claims: list[ClaimDto], source_paths: list[str]) -> list[str]:
        candidates: list[str] = list(_TAG_TOKEN.findall(title.casefold()))
        for claim in claims:
            candidates.append(claim.kind.value.casefold())
            candidates.extend(_TAG_TOKEN.findall(claim.statement.casefold())[:5])
        for path in source_paths:
            candidates.extend(_TAG_TOKEN.findall(PurePosixPath(path).stem.casefold()))
        return cls._ordered_unique(candidates)[:20]

    @staticmethod
    def _ordered_unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))

    @staticmethod
    def _duplicate_prose_count(markdown: str) -> int:
        seen: set[str] = set()
        duplicates = 0
        for block in re.split(r"\n{2,}", markdown):
            stripped = block.strip()
            if len(stripped) < 60 or stripped.startswith(("#", "```", "~~~", "|", "- ")):
                continue
            normalized = " ".join(_SOURCE_CITATION.sub("", stripped).casefold().split())
            if normalized in seen:
                duplicates += 1
            else:
                seen.add(normalized)
        return duplicates
