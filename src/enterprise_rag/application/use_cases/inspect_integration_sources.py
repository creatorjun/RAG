from __future__ import annotations

from enterprise_rag.application.dto.long_document import (
    ChunkingConfigDto,
    ChunkSourceDto,
    IntegrationInputDto,
    LongTextChunkDto,
    TextDocumentDto,
)
from enterprise_rag.application.ports.long_document import (
    LongDocumentChunkerPort,
    TextDocumentCollectionPort,
)
from enterprise_rag.application.progress import ProgressReporter
from enterprise_rag.domain.errors import revision_error


class InspectIntegrationSources:
    def __init__(
        self,
        source: TextDocumentCollectionPort,
        chunker: LongDocumentChunkerPort,
        chunking_config: ChunkingConfigDto,
    ) -> None:
        self._source = source
        self._chunker = chunker
        self._chunking_config = chunking_config

    async def execute(self, reporter: ProgressReporter) -> IntegrationInputDto:
        reporter.emit(0, "discovering", "원본 문서를 찾는 중")
        paths = await self._source.list_relative_paths()
        if not paths:
            raise revision_error("NO_TEXT_DOCUMENTS")
        if len(paths) != len(set(paths)):
            raise revision_error("CHUNK_COVERAGE_FAILED")

        documents: list[TextDocumentDto] = []
        chunks: list[LongTextChunkDto] = []
        chunk_sources: list[ChunkSourceDto] = []
        chunk_ids: set[str] = set()
        for document_index, path in enumerate(paths, start=1):
            document = await self._source.read(path)
            if document.relative_path != path:
                raise revision_error("CHUNK_COVERAGE_FAILED")
            chunk_set = await self._chunker.chunk(document, self._chunking_config)
            if not chunk_set.coverage.complete or chunk_set.relative_path != path:
                raise revision_error(
                    "CHUNK_COVERAGE_FAILED",
                    {"revision_id": document.revision_id},
                )
            documents.append(document)
            for chunk in chunk_set.chunks:
                if chunk.chunk_id in chunk_ids:
                    raise revision_error("DUPLICATE_PLAN_ITEM", {"stage": "inspection"})
                chunk_ids.add(chunk.chunk_id)
                chunks.append(chunk)
                chunk_sources.append(ChunkSourceDto(chunk.chunk_id, path))
            reporter.emit(
                5 + round(15 * document_index / len(paths)),
                "reading",
                "원본 문서를 읽고 청크로 분할하는 중",
                document_index,
                len(paths),
                "documents",
            )
        if not chunks or len(chunk_sources) != len(chunks):
            raise revision_error("NO_TEXT_DOCUMENTS")
        return IntegrationInputDto(tuple(documents), tuple(chunks), tuple(chunk_sources))
