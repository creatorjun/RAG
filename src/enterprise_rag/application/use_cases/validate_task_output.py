from __future__ import annotations

import re

from enterprise_rag.application.dto.claims import ClaimLedgerDto
from enterprise_rag.application.dto.tasks import (
    TaskOutputDto,
    TaskPacketDto,
    TaskValidationReportDto,
)
from enterprise_rag.domain.claims import ClaimRelationType

_EVIDENCE_MARKER = re.compile(r"\[evidence:(evidence:sha256:[0-9a-f]{64})\]")


class ValidateTaskOutput:
    def execute(
        self,
        packet: TaskPacketDto,
        ledger: ClaimLedgerDto,
        output: TaskOutputDto,
    ) -> TaskValidationReportDto:
        errors: set[str] = set()
        if output.task_id != packet.task_id:
            errors.add("TASK_ID_MISMATCH")
        if output.completion_marker != "TASK_COMPLETE":
            errors.add("OUTPUT_INCOMPLETE")

        required_sections = set(packet.required_sections)
        output_sections = {section.section_key for section in output.sections}
        if required_sections - output_sections:
            errors.add("REQUIRED_SECTION_MISSING")
        if output_sections - required_sections:
            errors.add("UNPLANNED_SECTION")

        claim_by_id = {claim.claim_id: claim for claim in ledger.claims}
        visible_claims = set(packet.owned_claim_ids) | set(packet.context_claim_ids)
        allowed_evidence = set(packet.allowed_evidence_ids)
        used_owned_claims: set[str] = set()
        used_claims: set[str] = set()
        used_evidence: set[str] = set()
        combined_markdown = "\n".join(section.markdown for section in output.sections)
        for section in output.sections:
            section_claims = set(section.used_claim_ids)
            section_evidence = set(section.used_evidence_ids)
            if not section_claims.issubset(visible_claims):
                errors.add("CLAIM_NOT_ALLOWED")
            if not section_evidence.issubset(allowed_evidence):
                errors.add("EVIDENCE_NOT_ALLOWED")
            marker_matches = _EVIDENCE_MARKER.findall(section.markdown)
            marker_evidence = set(marker_matches)
            if section.markdown.count("[evidence:") != len(marker_matches):
                errors.add("EVIDENCE_MARKER_MALFORMED")
            if "[source:" in section.markdown:
                errors.add("SOURCE_MARKER_NOT_ALLOWED")
            if section.markdown.count("```") % 2:
                errors.add("MARKDOWN_INCOMPLETE")
            if marker_evidence != section_evidence:
                errors.add("EVIDENCE_MARKER_MISMATCH")
            for claim_id in section_claims:
                claim = claim_by_id.get(claim_id)
                if claim is None:
                    errors.add("CLAIM_NOT_FOUND")
                    continue
                if not set(claim.evidence_ids).issubset(section_evidence):
                    errors.add("CLAIM_EVIDENCE_MISSING")
            used_owned_claims.update(section_claims & set(packet.owned_claim_ids))
            used_claims.update(section_claims)
            used_evidence.update(section_evidence)
        if used_owned_claims != set(packet.owned_claim_ids):
            errors.add("OWNED_CLAIM_MISSING")
        required_owned_evidence: set[str] = set()
        for claim_id in packet.owned_claim_ids:
            claim = claim_by_id.get(claim_id)
            if claim is None:
                errors.add("CLAIM_NOT_FOUND")
            else:
                required_owned_evidence.update(claim.evidence_ids)
        if not required_owned_evidence.issubset(used_evidence):
            errors.add("OWNED_EVIDENCE_MISSING")
        for claim_id in packet.owned_claim_ids:
            claim = claim_by_id.get(claim_id)
            if claim is None:
                continue
            if any(value not in combined_markdown for value in claim.preconditions):
                errors.add("CLAIM_PRECONDITION_MISSING")
            if any(value not in combined_markdown for value in claim.commands):
                errors.add("CLAIM_COMMAND_MISSING")
            if any(value not in combined_markdown for value in claim.warnings):
                errors.add("CLAIM_WARNING_MISSING")

        required_conflicts = {
            claim_id
            for relation in packet.relations
            if relation.relation is ClaimRelationType.CONFLICT
            for claim_id in (relation.left_claim_id, relation.right_claim_id)
        }
        if not required_conflicts.issubset(set(output.conflict_claim_ids)):
            errors.add("CONFLICT_NOT_EXPOSED")
        if not required_conflicts.issubset(used_claims):
            errors.add("CONFLICT_CONTENT_MISSING")
        if not set(output.conflict_claim_ids).issubset(visible_claims):
            errors.add("CONFLICT_CLAIM_NOT_ALLOWED")
        return TaskValidationReportDto(
            task_id=packet.task_id,
            valid=not errors,
            error_codes=tuple(sorted(errors)),
        )
