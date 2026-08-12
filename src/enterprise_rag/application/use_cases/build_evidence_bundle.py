from __future__ import annotations

import hashlib

from enterprise_rag.application.dto.evidence import EvidenceBundleDto, EvidenceItemDto
from enterprise_rag.application.dto.long_document import IntegrationInputDto
from enterprise_rag.application.progress import ProgressReporter
from enterprise_rag.domain.errors import revision_error


class BuildEvidenceBundle:
    def execute(
        self,
        integration_input: IntegrationInputDto,
        reporter: ProgressReporter | None = None,
    ) -> EvidenceBundleDto:
        source_by_chunk = integration_input.chunk_source_by_id
        if len(source_by_chunk) != len(integration_input.chunks):
            raise revision_error("EVIDENCE_COVERAGE_FAILED")
        document_by_path = {
            document.relative_path: document for document in integration_input.documents
        }
        if len(document_by_path) != len(integration_input.documents):
            raise revision_error("EVIDENCE_COVERAGE_FAILED")

        items: list[EvidenceItemDto] = []
        for chunk in integration_input.chunks:
            path = source_by_chunk.get(chunk.chunk_id)
            if path is None:
                raise revision_error("EVIDENCE_COVERAGE_FAILED")
            document = document_by_path.get(path)
            if document is None or chunk.revision_id != document.revision_id:
                raise revision_error("EVIDENCE_COVERAGE_FAILED")
            identity = (
                f"{document.source_sha256}\0{path}\0{chunk.primary_span.start_char}\0"
                f"{chunk.primary_span.end_char}\0{chunk.content_sha256}"
            )
            evidence_id = "evidence:sha256:" + hashlib.sha256(
                identity.encode("utf-8")
            ).hexdigest()
            try:
                items.append(
                    EvidenceItemDto(
                        evidence_id=evidence_id,
                        chunk_id=chunk.chunk_id,
                        revision_id=chunk.revision_id,
                        relative_path=path,
                        source_sha256=document.source_sha256,
                        ordinal=chunk.ordinal,
                        start_char=chunk.primary_span.start_char,
                        end_char=chunk.primary_span.end_char,
                        content_sha256=chunk.content_sha256,
                        text=chunk.primary_text,
                    )
                )
            except ValueError as error:
                raise revision_error("EVIDENCE_COVERAGE_FAILED") from error
        try:
            bundle = EvidenceBundleDto(
                items=tuple(items),
                source_document_count=len(integration_input.documents),
                source_structure_count=len(integration_input.chunks),
            )
        except ValueError as error:
            raise revision_error("EVIDENCE_COVERAGE_FAILED") from error
        if reporter is not None:
            reporter.emit(
                21,
                "building_evidence",
                "원본 Evidence를 구성하는 중",
                len(bundle.items),
                bundle.source_structure_count,
                "evidence",
            )
        return bundle
