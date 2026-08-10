<!-- docs/contracts.md -->
# 포트·DTO·워커 메시지 계약

## 1. 계약 범위

이 문서는 `application` 계층과 `infrastructure` 계층 사이의 공개 경계를 정의한다. 구현은 이름과 패키지 위치를 바꿀 수 없으며, 변경이 필요하면 스키마 버전과 문서를 함께 갱신한다.

## 2. 공통 타입

```python
from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Generic, Protocol, TypeVar

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    items: tuple[T, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class StoredObject:
    object_key: str
    sha256: str
    byte_count: int
    media_type: str
```

문자열 ID는 런타임에서 `NewType` 또는 불변 값 객체로 분리한다. 서로 다른 ID 타입 간 암시적 변환을 금지한다.

## 3. Source 계약

```python
class CandidateChange(StrEnum):
    NEW = "new"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class DocumentCandidate:
    source_id: str
    external_key: str
    source_version: str
    title: str
    declared_mime_type: str | None
    byte_count: int | None
    source_modified_at: datetime | None
    metadata: Mapping[str, JsonValue]
    acl_snapshot: "AclSnapshot"
    change_hint: CandidateChange


@dataclass(frozen=True, slots=True)
class SourceObject:
    candidate: DocumentCandidate
    detected_mime_type: str
    local_snapshot_key: str
    content_sha256: str
    byte_count: int


class DocumentSourcePort(Protocol):
    async def inventory(
        self,
        source_id: str,
        scope: Mapping[str, JsonValue],
        cursor: str | None,
        page_size: int,
    ) -> Page[DocumentCandidate]: ...

    async def snapshot(
        self,
        candidate: DocumentCandidate,
        destination: "ObjectWriterPort",
        cancellation: "CancellationToken",
    ) -> SourceObject: ...

    async def close(self) -> None: ...
```

### 3.1 Source 보장

- `inventory`는 같은 cursor와 변하지 않은 소스에서 안정된 순서를 반환한다.
- `external_key`는 소스 내에서 유일하고 페이지 이동이나 제목 변경으로 바뀌지 않는다.
- `snapshot`은 읽기 전후 변경을 감지하고 불안정한 원본을 성공으로 반환하지 않는다.
- 반환된 `content_sha256`은 저장 객체를 다시 읽어 검증 가능하다.
- 소스 삭제는 기존 저장 객체를 삭제하지 않는다.

### 3.2 Folder Revision 계약

```python
class RevisionRunState(StrEnum):
    PREPARED = "prepared"
    FINALIZED = "finalized"


class FileChangeStatus(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class RevisionRunDto:
    run_id: str
    state: RevisionRunState
    input_manifest_sha256: str
    input_file_count: int
    documents_relative_root: str


@dataclass(frozen=True, slots=True)
class FileComparisonDto:
    relative_path: str
    status: FileChangeStatus
    before_sha256: str | None
    after_sha256: str | None
    before_byte_count: int | None
    after_byte_count: int | None
    diff_relative_path: str | None


@dataclass(frozen=True, slots=True)
class FolderComparisonDto:
    run_id: str
    files: tuple[FileComparisonDto, ...]
    report_sha256: str


class DocumentWorkspacePort(Protocol):
    async def prepare_run(self, run_id: str) -> RevisionRunDto: ...

    async def open_document_writer(
        self,
        run_id: str,
        relative_path: str,
    ) -> "DocumentWriterPort": ...

    async def compare_run(self, run_id: str) -> FolderComparisonDto: ...

    async def finalize_run(self, run_id: str) -> RevisionRunDto: ...
```

- `prepare_run`은 기존 run을 절대 덮어쓰지 않고 before 입력 해시를 고정한 뒤에만 성공한다.
- writer는 정규화한 상대 경로가 현재 run의 `documents` 내부일 때만 열린다.
- before, 다른 run, `_reports`, manifest에 대한 일반 writer 요청은 거부한다.
- `compare_run`은 상대 경로 정렬과 SHA-256 비교가 결정적이어야 한다.
- `finalize_run`은 비교 보고서와 입력 매니페스트를 검증하고 이후 writer 생성을 거부한다.
- 포트 구현은 Confluence API, 비밀 저장소, 네트워크 클라이언트에 의존하지 않는다.

## 4. Parser와 Chunker 계약

```python
class ElementType(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    CODE_BLOCK = "code_block"
    IMAGE_CAPTION = "image_caption"
    PAGE_BREAK = "page_break"


@dataclass(frozen=True, slots=True)
class NormalizedElement:
    ordinal: int
    element_type: ElementType
    text: str
    heading_level: int | None
    language: str | None
    source_spans: tuple["SourceSpanDto", ...]
    attributes: Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class NormalizedDocumentDto:
    schema_version: int
    revision_id: str
    parser_id: str
    parser_version: str
    title: str
    elements: tuple[NormalizedElement, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ParseRequest:
    revision_id: str
    source_object: StoredObject
    detected_mime_type: str
    options: Mapping[str, JsonValue]


class DocumentParserPort(Protocol):
    def supports(self, detected_mime_type: str) -> bool: ...

    async def parse(
        self,
        request: ParseRequest,
        cancellation: "CancellationToken",
    ) -> NormalizedDocumentDto: ...


@dataclass(frozen=True, slots=True)
class ChunkingConfigDto:
    tokenizer_id: str
    target_tokens: int
    max_tokens: int
    overlap_ratio: float
    preserve_tables: bool
    preserve_code_blocks: bool


@dataclass(frozen=True, slots=True)
class ChunkDto:
    chunk_id: str
    revision_id: str
    ordinal: int
    display_text: str
    embedding_text: str
    token_count: int
    content_sha256: str
    heading_path: tuple[str, ...]
    source_spans: tuple["SourceSpanDto", ...]
    parent_chunk_id: str | None
    previous_chunk_id: str | None
    next_chunk_id: str | None


class ChunkerPort(Protocol):
    async def chunk(
        self,
        document: NormalizedDocumentDto,
        config: ChunkingConfigDto,
        cancellation: "CancellationToken",
    ) -> tuple[ChunkDto, ...]: ...
```

### 4.1 Parser·Chunker 보장

- 모든 비어 있지 않은 정규화 요소는 최소 하나의 출처 범위를 가진다.
- `ordinal`은 0부터 연속 증가한다.
- 청크 표시 텍스트를 정규화 문서 요소에 역매핑할 수 있어야 한다.
- 어떤 청크도 `max_tokens`를 넘지 않는다. 단일 비분할 구조가 상한을 넘으면 성공 대신 `ChunkBoundaryError`를 반환한다.
- 이전·다음 청크 연결은 같은 리비전 내에서 대칭이어야 한다.
- 같은 입력과 설정에서 청크 ID와 순서가 결정적이어야 한다.

## 5. Embedder와 Vector Index 계약

```python
@dataclass(frozen=True, slots=True)
class EmbeddingModelDescriptor:
    model_id: str
    revision: str
    dimension: int
    normalized: bool
    modes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EmbeddingInput:
    item_id: str
    text: str
    token_count: int


@dataclass(frozen=True, slots=True)
class DenseEmbedding:
    item_id: str
    values: tuple[float, ...]


class EmbedderPort(Protocol):
    async def descriptor(self) -> EmbeddingModelDescriptor: ...

    async def embed(
        self,
        items: Sequence[EmbeddingInput],
        cancellation: "CancellationToken",
    ) -> tuple[DenseEmbedding, ...]: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class VectorRecord:
    vector_id: str
    item_id: str
    values: tuple[float, ...]
    metadata: Mapping[str, JsonScalar]


@dataclass(frozen=True, slots=True)
class VectorFilter:
    allowed_acl_fingerprints: tuple[str, ...]
    allowed_security_labels: tuple[str, ...]
    document_ids: tuple[str, ...]
    language: str | None
    active_only: bool


@dataclass(frozen=True, slots=True)
class SearchHit:
    vector_id: str
    item_id: str
    score: float
    generation_id: str


class VectorIndexPort(Protocol):
    async def build_generation(
        self,
        generation_id: str,
        records: AsyncIterator[VectorRecord],
        expected_count: int,
        cancellation: "CancellationToken",
    ) -> "VectorGenerationManifest": ...

    async def verify_generation(
        self,
        generation_id: str,
    ) -> "VectorGenerationManifest": ...

    async def activate_generation(self, generation_id: str) -> None: ...

    async def search(
        self,
        query: tuple[float, ...],
        top_k: int,
        filters: VectorFilter,
    ) -> tuple[SearchHit, ...]: ...

    async def close(self) -> None: ...
```

### 5.1 Vector 보장

- 모든 벡터는 descriptor 차원과 일치하고 유한값만 포함한다.
- 입력이 L2 정규화되지 않았으면 어댑터가 거부한다.
- 검색 점수는 정규화 벡터의 inner product이며 범위는 부동소수 오차를 포함한 -1~1이다.
- 비활성 세대는 검색에 사용되지 않는다.
- 세대 활성화는 실패 시 이전 세대를 유지한다.
- ACL과 보안 등급 필터는 결과 반환 전에 적용된다.

## 6. Language Model 계약

```python
class GenerationPurpose(StrEnum):
    CLAIM_EXTRACTION = "claim_extraction"
    CLAIM_VALIDATION = "claim_validation"
    MAP_SYNTHESIS = "map_synthesis"
    REDUCE_SYNTHESIS = "reduce_synthesis"


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    model_id: str
    revision: str
    quantization: str
    runtime: str
    maximum_context_tokens: int


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    request_id: str
    purpose: GenerationPurpose
    system_prompt_version: str
    messages: tuple["MessageDto", ...]
    response_schema: Mapping[str, JsonValue]
    input_token_count: int
    max_output_tokens: int
    temperature: float
    seed: int | None
    deadline_at: datetime


@dataclass(frozen=True, slots=True)
class GenerationUsage:
    input_tokens: int
    output_tokens: int
    first_token_ms: int
    total_ms: int


@dataclass(frozen=True, slots=True)
class GenerationResponse:
    request_id: str
    model: ModelDescriptor
    parsed_output: Mapping[str, JsonValue]
    usage: GenerationUsage
    repair_attempted: bool


class LanguageModelPort(Protocol):
    async def descriptor(self) -> ModelDescriptor: ...

    async def generate_structured(
        self,
        request: GenerationRequest,
        cancellation: "CancellationToken",
    ) -> GenerationResponse: ...

    async def close(self) -> None: ...
```

### 6.1 생성 정책

| 목적 | 기본 temperature | seed | 출력 상한 | 교정 재시도 |
| --- | ---: | --- | ---: | ---: |
| 주장 추출 | 0.0 | 고정 | 2048 | 1 |
| 주장 검증 | 0.0 | 고정 | 2048 | 1 |
| Map 합성 | 0.1 | 고정 | 3072 | 1 |
| Reduce 합성 | 0.1 | 고정 | 4096 | 1 |

`input_token_count + max_output_tokens + reserved_tokens`가 승인 컨텍스트를 넘으면 모델을 호출하지 않고 `TokenBudgetExceededError`를 반환한다. `reserved_tokens` 기본값은 512다.

## 7. Web Search 계약

```python
class EgressDecision(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    REVIEW = "review"


@dataclass(frozen=True, slots=True)
class SearchQueryCandidate:
    query_id: str
    claim_id: str
    original_query: str
    public_entities: tuple[str, ...]
    requested_domains: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SanitizedSearchQuery:
    query_id: str
    transmitted_query: str
    allowed_domains: tuple[str, ...]
    redaction_types: tuple[str, ...]
    policy_version: str


@dataclass(frozen=True, slots=True)
class EgressEvaluation:
    decision: EgressDecision
    sanitized_query: SanitizedSearchQuery | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SearchResultDto:
    rank: int
    url: str
    title: str
    snippet: str
    publisher: str | None
    published_at: datetime | None


class WebSearchPort(Protocol):
    async def search(
        self,
        query: SanitizedSearchQuery,
        max_results: int,
        cancellation: "CancellationToken",
    ) -> tuple[SearchResultDto, ...]: ...

    async def fetch_evidence(
        self,
        result: SearchResultDto,
        cancellation: "CancellationToken",
    ) -> "FetchedEvidenceDto": ...

    async def close(self) -> None: ...
```

### 7.1 Web 보장

- `DisabledSearchPort`는 모든 호출을 `ExternalSearchDisabledError`로 거부한다.
- 검색 어댑터는 `original_query` 타입을 받을 수 없다.
- 실제 HTTP 요청은 `transmitted_query`만 사용한다.
- 리디렉션마다 정책을 다시 평가한다.
- 사설·루프백·링크 로컬·멀티캐스트 주소는 DNS 결과 단계에서 거부한다.
- 응답은 압축 해제 후 크기 상한을 적용한다.
- 검색 스니펫은 근거로 확정하지 않고 fetch에 성공한 본문만 `ExternalEvidence`로 저장한다.

## 8. Metadata와 Artifact 계약

```python
class MetadataRepositoryPort(Protocol):
    async def transaction(self) -> "TransactionContext": ...

    async def get_revision(self, revision_id: str) -> "DocumentRevision | None": ...

    async def list_ready_jobs(
        self,
        now: datetime,
        limit: int,
    ) -> tuple["JobDto", ...]: ...

    async def claim_job(
        self,
        job_id: str,
        worker_id: str,
        lease_until: datetime,
    ) -> bool: ...

    async def complete_stage(
        self,
        stage_result: "StageResultDto",
        follow_up_jobs: Sequence["NewJobDto"],
    ) -> None: ...

    async def close(self) -> None: ...


class ObjectWriterPort(Protocol):
    async def write_stream(
        self,
        media_type: str,
        chunks: AsyncIterator[bytes],
        cancellation: "CancellationToken",
    ) -> StoredObject: ...


class ArtifactRepositoryPort(Protocol):
    async def begin_generation(
        self,
        generation_id: str,
    ) -> "ArtifactGenerationWriter": ...

    async def verify_generation(
        self,
        generation_id: str,
    ) -> "ArtifactGenerationManifest": ...

    async def activate_generation(self, generation_id: str) -> None: ...

    async def active_generation(self) -> str | None: ...
```

저장 포트의 성공 반환은 바이트가 영구 저장되고 체크섬을 다시 검증할 수 있음을 뜻한다. 임시 파일만 존재하는 상태는 성공이 아니다.

## 9. Job Queue와 Worker 계약

### 9.1 작업 상태

```python
class JobStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    QUARANTINED = "quarantined"
    CANCELLED = "cancelled"
```

허용 상태 전이는 다음과 같다.

```text
PENDING -> READY
PENDING -> CANCELLED
READY -> RUNNING
READY -> CANCELLED
RUNNING -> COMPLETED
RUNNING -> RETRY_WAIT
RUNNING -> FAILED
RUNNING -> QUARANTINED
RUNNING -> CANCELLED
RETRY_WAIT -> READY
RETRY_WAIT -> CANCELLED
```

최종 상태에서 다른 상태로 전이하지 않는다.

### 9.2 워커 Envelope

```json
{
  "schema_version": 1,
  "message_id": "019...",
  "correlation_id": "019...",
  "causation_id": "019...",
  "sent_at": "2026-08-10T06:00:00Z",
  "deadline_at": "2026-08-10T06:10:00Z",
  "message_type": "execute_job",
  "payload": {}
}
```

필수 메시지 유형은 `worker_ready`, `execute_job`, `cancel_job`, `job_progress`, `job_succeeded`, `job_failed`, `heartbeat`, `shutdown`, `shutdown_ack`다.

### 9.3 워커 프로토콜

- 워커는 시작 후 30초 안에 `worker_ready`를 보내야 한다.
- 실행 중 5초마다 heartbeat를 보낸다.
- Coordinator는 heartbeat 3회 누락 시 워커를 비정상으로 판정한다.
- `cancel_job` 수신 후 15초 안에 종료 결과를 반환해야 한다.
- 성공 payload는 CAS object key 또는 DB에 검증 가능한 staging ID를 포함한다.
- Coordinator만 결과를 정본 DB 상태로 커밋한다.
- 중복 `message_id`는 재실행하지 않고 기존 응답을 반환한다.
- 워커 protocol major version이 다르면 연결을 거부한다.

## 10. 취소와 Deadline 계약

```python
class CancellationToken(Protocol):
    @property
    def is_cancelled(self) -> bool: ...

    def raise_if_cancelled(self) -> None: ...
```

- 모든 긴 루프는 문서, 페이지, 청크 배치, 생성 조각 경계에서 취소를 확인한다.
- deadline이 지난 요청은 새 외부 호출이나 모델 호출을 시작하지 않는다.
- SQLite 트랜잭션 커밋 중 취소는 커밋 또는 롤백을 완료한 뒤 반영한다.
- 취소는 실패 횟수에 포함하지 않는다.
- 프로세스 강제 종료는 정상 취소 제한 시간을 초과한 경우에만 수행한다.

## 11. 예외 분류

```python
class ErrorCategory(StrEnum):
    TRANSIENT_SOURCE = "transient_source"
    TRANSIENT_NETWORK = "transient_network"
    RESOURCE_PRESSURE = "resource_pressure"
    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_FORMAT = "unsupported_format"
    DATA_CORRUPTION = "data_corruption"
    SECURITY_BLOCK = "security_block"
    MODEL_OUTPUT = "model_output"
    CONSISTENCY = "consistency"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class ApplicationError(Exception):
    code: str
    category: ErrorCategory
    retryable: bool
    safe_message: str
    context: Mapping[str, JsonScalar]
```

| 범주 | 기본 재시도 | 최종 처리 |
| --- | ---: | --- |
| `TRANSIENT_SOURCE` | 3 | 실패 |
| `TRANSIENT_NETWORK` | 3 | 내부 전용 검증 또는 실패 |
| `RESOURCE_PRESSURE` | 3 | 운영 경고 후 실패 |
| `INVALID_INPUT` | 0 | 격리 |
| `UNSUPPORTED_FORMAT` | 0 | 격리 |
| `DATA_CORRUPTION` | 0 | 격리와 보안 이벤트 |
| `SECURITY_BLOCK` | 0 | 차단 또는 검토 |
| `MODEL_OUTPUT` | 교정 1회 | 검토 큐 |
| `CONSISTENCY` | 0 | 시스템 복구 모드 |
| `CANCELLED` | 0 | 취소 |
| `INTERNAL` | 1 | 실패와 운영 경고 |

예외 context에는 원문, 검색 원문 질의, 비밀값, 사용자 개인정보, 전체 로컬 경로를 포함하지 않는다.

폴더 리비전 경계의 고정 오류 코드는 다음과 같다.

| 코드 | 범주 | 재시도 |
| --- | --- | ---: |
| `BEFORE_ROOT_NOT_READABLE` | `SECURITY_BLOCK` | 0 |
| `BEFORE_ROOT_MUTABLE` | `SECURITY_BLOCK` | 0 |
| `BEFORE_AFTER_OVERLAP` | `SECURITY_BLOCK` | 0 |
| `PATH_ESCAPE` | `SECURITY_BLOCK` | 0 |
| `LINK_NOT_ALLOWED` | `SECURITY_BLOCK` | 0 |
| `RUN_ALREADY_EXISTS` | `INVALID_INPUT` | 0 |
| `RUN_FINALIZED` | `INVALID_INPUT` | 0 |
| `INPUT_HASH_CHANGED` | `CONSISTENCY` | 0 |
| `COMPARISON_INCOMPLETE` | `CONSISTENCY` | 0 |

## 12. 시간·난수·해시 포트

재현성과 테스트 격리를 위해 다음 포트를 사용한다.

```python
class ClockPort(Protocol):
    def now(self) -> datetime: ...


class IdGeneratorPort(Protocol):
    def new_trace_id(self) -> str: ...


class HashPort(Protocol):
    def sha256_bytes(self, value: bytes) -> str: ...

    def sha256_text(self, value: str) -> str: ...
```

도메인 결정적 ID는 `IdGeneratorPort`가 아니라 정규화된 입력과 `HashPort`로 만든다. 실행, 작업, 승인, 감사 ID만 UUIDv7 또는 ULID 계열 시간 정렬 ID를 사용한다.

## 13. 계약 테스트

각 포트 구현은 공통 계약 테스트 스위트를 통과해야 한다.

- 같은 입력에서 안정된 결과와 ID
- 취소와 deadline 준수
- 성공 반환 후 데이터 재검증
- 명시된 예외 분류
- close 멱등성
- 비밀·원문 없는 오류 메시지
- 경계값과 빈 페이지 처리
- 잘못된 schema version 거부
- 워커 중복 메시지 재실행 방지
- 저장·인덱스 활성화 실패 시 이전 세대 유지
