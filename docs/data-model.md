<!-- docs/data-model.md -->
# 데이터 모델과 영속성 상세 설계

## 1. 저장소 구성

| 저장소 | 저장 대상 | 정합성 단위 | 백업 단위 |
| --- | --- | --- | --- |
| SQLite | 메타데이터, 상태, ACL, 계보, 주장, 승인, 매니페스트 | 트랜잭션 | SQLite backup API 결과 |
| CAS 파일 저장소 | 원본, 정규화 JSON, 외부 근거 본문, 프롬프트·응답, 산출물 | SHA-256 객체 | 해시 디렉터리 |
| FAISS 세대 | dense 벡터 인덱스와 ID 맵 | 불변 세대 | 세대 디렉터리 |
| 로그 저장소 | 구조화 운영·감사 로그 | append-only 파일 | 날짜·크기 회전 파일 |
| Before/After 작업공간 | 불변 입력 스냅샷, 실행별 수정 문서, 비교 보고서 | 폴더 run | finalized run 디렉터리 |

SQLite에는 CAS 객체 키와 체크섬을 저장한다. DB 행이 참조하지 않는 임시 객체는 고아 정리 대상이며, DB가 참조하는 객체는 파일 보존 기간과 무관하게 삭제할 수 없다.

## 2. 저장 경로

```text
data/
├── before/
│   └── <dataset>/
└── after/
    └── runs/
        └── <run_id>/
            ├── documents/
            ├── _reports/
            └── run-manifest.json

var/
├── objects/
│   └── sha256/
│       └── ab/
│           └── cd/
│               └── abcdef...
├── database/
│   ├── metadata.sqlite3
│   ├── metadata.sqlite3-wal
│   └── metadata.sqlite3-shm
├── indexes/
│   └── vectors/
│       └── <generation_id>/
│           ├── index.faiss
│           ├── id-map.parquet
│           └── manifest.json
├── artifacts/
│   ├── generations/
│   │   └── <generation_id>/
│   └── current
├── staging/
│   └── <run_id>/
├── quarantine/
│   └── <revision_id>/
└── logs/
    ├── application.jsonl
    └── audit.jsonl
```

CAS object key 형식은 `sha256/ab/cd/<64-hex>`다. 경로 입력은 object key 생성기만 만들며 외부 입력을 직접 연결하지 않는다.

`data/before`는 DB와 CAS 밖의 승인 입력 경계지만 인제스천 즉시 CAS에 불변 스냅샷을 만든다. `data/after` finalized run은 사람이 검토하는 전달 산출물이므로 DB 매니페스트와 함께 백업한다.

## 3. ID와 시간 규칙

### 3.1 추적 ID

`run_id`, `job_id`, `approval_id`, `audit_event_id`, `message_id`는 UUIDv7 문자열을 사용한다. 소문자 하이픈 형식으로 저장하며 길이는 36자다.

### 3.2 결정적 ID

| ID | 정규화 입력 |
| --- | --- |
| `source_id` | `folder_snapshot`, 정규화 before root URI, 데이터셋 상대 경로 |
| `document_id` | source ID, external key |
| `revision_id` | document ID, source version, content SHA-256, ACL fingerprint |
| `normalized_id` | revision ID, parser ID, parser version, parser option hash |
| `chunk_id` | normalized ID, chunker version, ordinal, display text SHA-256 |
| `embedding_id` | chunk ID, model ID, model revision, embedding option hash |
| `cluster_id` | dedup generation ID, 정렬된 멤버 chunk ID |
| `claim_id` | 정규화 subject, predicate, object, 정렬된 source refs, prompt version |
| `evidence_id` | canonical URL, content SHA-256 |
| `artifact_id` | topic key, ACL fingerprint, evidence manifest hash, synthesis fingerprint |

결정적 ID는 `sha256:<64-hex>` 형식을 사용한다. 정규화 규칙이 바뀌면 구성요소 버전을 올려 기존 ID와 충돌하지 않게 한다.

### 3.3 시간

- SQLite에는 UTC ISO 8601 문자열 `YYYY-MM-DDTHH:MM:SS.ffffffZ`로 저장한다.
- 소스 수정 시각과 수집 시각을 분리한다.
- 소스가 제공하지 않은 게시·수정 시각을 추정해 저장하지 않는다.
- 만료와 리스 비교는 Coordinator의 단일 `ClockPort`를 사용한다.

## 4. SQLite 설정

애플리케이션 시작 시 다음 PRAGMA를 확인한다.

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;
PRAGMA temp_store = MEMORY;
```

쓰기 연결은 Coordinator 하나만 소유한다. 읽기 연결은 `mode=ro` URI로 열며 워커가 DB에 직접 쓰지 않는다.

## 5. 스키마 DDL

### 5.1 스키마와 객체 저장소

```sql
CREATE TABLE schema_migration (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE stored_object (
    object_key TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
    media_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    reference_count INTEGER NOT NULL DEFAULT 0 CHECK (reference_count >= 0)
);
```

`reference_count`는 최적화 힌트이며 삭제 가능성을 단독으로 결정하지 않는다. 실제 삭제 전에 참조 테이블을 다시 검사한다.

### 5.2 소스, 문서, ACL

```sql
CREATE TABLE document_source (
    source_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL CHECK (source_type IN ('folder_snapshot')),
    canonical_uri TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE acl_policy (
    acl_policy_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    security_label TEXT NOT NULL CHECK (
        security_label IN ('public', 'internal', 'confidential', 'restricted')
    ),
    created_at TEXT NOT NULL
);

CREATE TABLE acl_entry (
    acl_policy_id TEXT NOT NULL REFERENCES acl_policy(acl_policy_id) ON DELETE RESTRICT,
    principal_type TEXT NOT NULL CHECK (
        principal_type IN ('user', 'group', 'service', 'operator_only')
    ),
    principal_id TEXT NOT NULL,
    permission TEXT NOT NULL CHECK (permission IN ('read')),
    PRIMARY KEY (acl_policy_id, principal_type, principal_id, permission)
);

CREATE TABLE document (
    document_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES document_source(source_id) ON DELETE RESTRICT,
    external_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('active', 'deleted_at_source', 'disabled')
    ),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE (source_id, external_key)
);

CREATE TABLE document_revision (
    revision_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES document(document_id) ON DELETE RESTRICT,
    source_version TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    raw_object_key TEXT NOT NULL REFERENCES stored_object(object_key) ON DELETE RESTRICT,
    detected_mime_type TEXT NOT NULL,
    declared_mime_type TEXT,
    byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    source_modified_at TEXT,
    captured_at TEXT NOT NULL,
    acl_policy_id TEXT NOT NULL REFERENCES acl_policy(acl_policy_id) ON DELETE RESTRICT,
    metadata_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('captured', 'processing', 'ready', 'quarantined', 'failed')
    ),
    UNIQUE (document_id, source_version, content_sha256, acl_policy_id)
);

CREATE INDEX ix_revision_document_captured
ON document_revision(document_id, captured_at DESC);

CREATE INDEX ix_revision_content_hash
ON document_revision(content_sha256);
```

ACL이 바뀌면 내용이 같아도 새 리비전을 만든다. 이전 ACL이 적용된 파생물은 새 ACL로 덮어쓰지 않고 별도 재처리한다.

### 5.3 정규화와 청크

```sql
CREATE TABLE normalized_document (
    normalized_id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL REFERENCES document_revision(revision_id) ON DELETE RESTRICT,
    parser_id TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    options_hash TEXT NOT NULL,
    object_key TEXT NOT NULL REFERENCES stored_object(object_key) ON DELETE RESTRICT,
    element_count INTEGER NOT NULL CHECK (element_count >= 0),
    warning_count INTEGER NOT NULL CHECK (warning_count >= 0),
    content_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (revision_id, parser_id, parser_version, options_hash)
);

CREATE TABLE chunk (
    chunk_id TEXT PRIMARY KEY,
    normalized_id TEXT NOT NULL REFERENCES normalized_document(normalized_id) ON DELETE RESTRICT,
    revision_id TEXT NOT NULL REFERENCES document_revision(revision_id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    display_text TEXT NOT NULL CHECK (length(display_text) > 0),
    embedding_text TEXT NOT NULL CHECK (length(embedding_text) > 0),
    token_count INTEGER NOT NULL CHECK (token_count > 0),
    content_sha256 TEXT NOT NULL,
    heading_path_json TEXT NOT NULL,
    parent_chunk_id TEXT REFERENCES chunk(chunk_id) ON DELETE RESTRICT,
    previous_chunk_id TEXT REFERENCES chunk(chunk_id) ON DELETE RESTRICT,
    next_chunk_id TEXT REFERENCES chunk(chunk_id) ON DELETE RESTRICT,
    chunker_version TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE (normalized_id, ordinal, chunker_version)
);

CREATE TABLE chunk_source_span (
    chunk_id TEXT NOT NULL REFERENCES chunk(chunk_id) ON DELETE RESTRICT,
    span_ordinal INTEGER NOT NULL CHECK (span_ordinal >= 0),
    page_number INTEGER CHECK (page_number IS NULL OR page_number > 0),
    section_path_json TEXT NOT NULL,
    paragraph_index INTEGER CHECK (paragraph_index IS NULL OR paragraph_index >= 0),
    table_index INTEGER CHECK (table_index IS NULL OR table_index >= 0),
    row_index INTEGER CHECK (row_index IS NULL OR row_index >= 0),
    column_index INTEGER CHECK (column_index IS NULL OR column_index >= 0),
    start_offset INTEGER CHECK (start_offset IS NULL OR start_offset >= 0),
    end_offset INTEGER CHECK (end_offset IS NULL OR end_offset >= 0),
    PRIMARY KEY (chunk_id, span_ordinal),
    CHECK (
        page_number IS NOT NULL OR
        paragraph_index IS NOT NULL OR
        table_index IS NOT NULL OR
        start_offset IS NOT NULL
    ),
    CHECK (
        start_offset IS NULL OR end_offset IS NULL OR end_offset >= start_offset
    )
);

CREATE INDEX ix_chunk_revision_ordinal
ON chunk(revision_id, ordinal);

CREATE INDEX ix_chunk_content_hash
ON chunk(content_sha256);
```

### 5.4 분류와 임베딩

```sql
CREATE TABLE classification_run (
    classification_run_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    labeled_dataset_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (model_id, model_revision, policy_version, config_hash, labeled_dataset_version)
);

CREATE TABLE classification_result (
    classification_run_id TEXT NOT NULL REFERENCES classification_run(classification_run_id) ON DELETE RESTRICT,
    chunk_id TEXT NOT NULL REFERENCES chunk(chunk_id) ON DELETE RESTRICT,
    decision TEXT NOT NULL CHECK (
        decision IN ('technical', 'non_technical', 'uncertain')
    ),
    metadata_score REAL NOT NULL CHECK (metadata_score BETWEEN 0.0 AND 1.0),
    rule_score REAL NOT NULL CHECK (rule_score BETWEEN 0.0 AND 1.0),
    technical_similarity REAL NOT NULL CHECK (technical_similarity BETWEEN -1.0001 AND 1.0001),
    nontechnical_similarity REAL NOT NULL CHECK (nontechnical_similarity BETWEEN -1.0001 AND 1.0001),
    aggregate_score REAL NOT NULL CHECK (aggregate_score BETWEEN 0.0 AND 1.0),
    reason_codes_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (classification_run_id, chunk_id)
);

CREATE TABLE embedding_record (
    embedding_id TEXT PRIMARY KEY,
    chunk_id TEXT NOT NULL REFERENCES chunk(chunk_id) ON DELETE RESTRICT,
    model_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    normalized INTEGER NOT NULL CHECK (normalized IN (0, 1)),
    options_hash TEXT NOT NULL,
    vector_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (chunk_id, model_id, model_revision, options_hash)
);

CREATE INDEX ix_embedding_chunk
ON embedding_record(chunk_id);
```

벡터 값 자체는 활성 FAISS 세대와 세대 staging 파일에 저장하며 SQLite에는 벡터 무결성 메타데이터를 저장한다.

### 5.5 FAISS 세대

```sql
CREATE TABLE vector_generation (
    generation_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    index_type TEXT NOT NULL CHECK (index_type IN ('flat_ip', 'hnsw_ip')),
    config_hash TEXT NOT NULL,
    vector_count INTEGER NOT NULL CHECK (vector_count >= 0),
    directory_path TEXT NOT NULL UNIQUE,
    manifest_sha256 TEXT NOT NULL,
    index_sha256 TEXT NOT NULL,
    id_map_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('building', 'verified', 'active', 'retired', 'failed')
    ),
    created_at TEXT NOT NULL,
    verified_at TEXT,
    activated_at TEXT
);

CREATE TABLE vector_generation_member (
    generation_id TEXT NOT NULL REFERENCES vector_generation(generation_id) ON DELETE RESTRICT,
    faiss_position INTEGER NOT NULL CHECK (faiss_position >= 0),
    embedding_id TEXT NOT NULL REFERENCES embedding_record(embedding_id) ON DELETE RESTRICT,
    chunk_id TEXT NOT NULL REFERENCES chunk(chunk_id) ON DELETE RESTRICT,
    acl_policy_id TEXT NOT NULL REFERENCES acl_policy(acl_policy_id) ON DELETE RESTRICT,
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    PRIMARY KEY (generation_id, faiss_position),
    UNIQUE (generation_id, embedding_id)
);

CREATE UNIQUE INDEX ux_one_active_vector_generation
ON vector_generation(status)
WHERE status = 'active';
```

활성화 트랜잭션은 기존 `active`를 `retired`로 변경하고 새 `verified`를 `active`로 변경한다. 두 변경 사이 외부 검색을 허용하지 않는다.

### 5.6 중복 군집

```sql
CREATE TABLE dedup_generation (
    dedup_generation_id TEXT PRIMARY KEY,
    exact_algorithm TEXT NOT NULL,
    near_algorithm TEXT NOT NULL,
    embedding_model_id TEXT NOT NULL,
    embedding_model_revision TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('building', 'verified', 'active', 'retired', 'failed')
    ),
    created_at TEXT NOT NULL,
    activated_at TEXT
);

CREATE TABLE duplicate_cluster (
    cluster_id TEXT PRIMARY KEY,
    dedup_generation_id TEXT NOT NULL REFERENCES dedup_generation(dedup_generation_id) ON DELETE RESTRICT,
    canonical_chunk_id TEXT NOT NULL REFERENCES chunk(chunk_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (
        status IN ('confirmed', 'review_required', 'conflict')
    ),
    canonical_reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE duplicate_member (
    cluster_id TEXT NOT NULL REFERENCES duplicate_cluster(cluster_id) ON DELETE RESTRICT,
    chunk_id TEXT NOT NULL REFERENCES chunk(chunk_id) ON DELETE RESTRICT,
    relation TEXT NOT NULL CHECK (
        relation IN ('exact', 'near_text', 'semantic')
    ),
    exact_match INTEGER NOT NULL CHECK (exact_match IN (0, 1)),
    near_text_score REAL,
    semantic_score REAL,
    is_canonical INTEGER NOT NULL CHECK (is_canonical IN (0, 1)),
    reason_codes_json TEXT NOT NULL,
    PRIMARY KEY (cluster_id, chunk_id)
);

CREATE UNIQUE INDEX ux_cluster_one_canonical
ON duplicate_member(cluster_id)
WHERE is_canonical = 1;
```

### 5.7 주장, 외부 근거, 검증

```sql
CREATE TABLE claim (
    claim_id TEXT PRIMARY KEY,
    subject TEXT NOT NULL CHECK (length(trim(subject)) > 0),
    predicate TEXT NOT NULL CHECK (length(trim(predicate)) > 0),
    object_value TEXT NOT NULL CHECK (length(trim(object_value)) > 0),
    claim_type TEXT NOT NULL CHECK (
        claim_type IN (
            'version', 'date', 'security', 'compatibility',
            'configuration', 'internal_policy', 'other'
        )
    ),
    external_verifiability TEXT NOT NULL CHECK (
        external_verifiability IN ('low', 'medium', 'high')
    ),
    freshness_risk TEXT NOT NULL CHECK (
        freshness_risk IN ('low', 'medium', 'high')
    ),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0.0 AND 1.0),
    extraction_run_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE claim_source (
    claim_id TEXT NOT NULL REFERENCES claim(claim_id) ON DELETE RESTRICT,
    chunk_id TEXT NOT NULL REFERENCES chunk(chunk_id) ON DELETE RESTRICT,
    span_ordinal INTEGER NOT NULL,
    quote_text TEXT NOT NULL CHECK (length(quote_text) > 0),
    quote_sha256 TEXT NOT NULL,
    PRIMARY KEY (claim_id, chunk_id, span_ordinal),
    FOREIGN KEY (chunk_id, span_ordinal)
        REFERENCES chunk_source_span(chunk_id, span_ordinal)
        ON DELETE RESTRICT
);

CREATE TABLE search_query (
    query_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES claim(claim_id) ON DELETE RESTRICT,
    original_query_object_key TEXT NOT NULL REFERENCES stored_object(object_key) ON DELETE RESTRICT,
    transmitted_query TEXT,
    decision TEXT NOT NULL CHECK (decision IN ('allow', 'block', 'review')),
    reason_codes_json TEXT NOT NULL,
    redaction_types_json TEXT NOT NULL,
    allowed_domains_json TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (
        (decision = 'allow' AND transmitted_query IS NOT NULL) OR
        (decision <> 'allow' AND transmitted_query IS NULL)
    )
);

CREATE TABLE external_evidence (
    evidence_id TEXT PRIMARY KEY,
    canonical_url TEXT NOT NULL,
    publisher TEXT NOT NULL,
    title TEXT NOT NULL,
    published_at TEXT,
    retrieved_at TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    object_key TEXT NOT NULL REFERENCES stored_object(object_key) ON DELETE RESTRICT,
    trust_tier TEXT NOT NULL CHECK (
        trust_tier IN ('primary', 'authoritative', 'secondary', 'unknown')
    ),
    content_type TEXT NOT NULL,
    http_status INTEGER NOT NULL CHECK (http_status BETWEEN 200 AND 299),
    UNIQUE (canonical_url, content_sha256)
);

CREATE TABLE query_evidence (
    query_id TEXT NOT NULL REFERENCES search_query(query_id) ON DELETE RESTRICT,
    evidence_id TEXT NOT NULL REFERENCES external_evidence(evidence_id) ON DELETE RESTRICT,
    rank INTEGER NOT NULL CHECK (rank > 0),
    PRIMARY KEY (query_id, evidence_id)
);

CREATE TABLE validation_report (
    validation_report_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES claim(claim_id) ON DELETE RESTRICT,
    relation TEXT NOT NULL CHECK (
        relation IN (
            'confirmed', 'outdated', 'contradicted',
            'not_applicable', 'insufficient_evidence'
        )
    ),
    internal_current_state TEXT NOT NULL,
    external_public_state TEXT,
    proposed_change TEXT,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0.0 AND 1.0),
    requires_human_review INTEGER NOT NULL CHECK (requires_human_review IN (0, 1)),
    validation_run_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE validation_evidence (
    validation_report_id TEXT NOT NULL REFERENCES validation_report(validation_report_id) ON DELETE RESTRICT,
    evidence_id TEXT NOT NULL REFERENCES external_evidence(evidence_id) ON DELETE RESTRICT,
    support_relation TEXT NOT NULL CHECK (
        support_relation IN ('supports', 'contradicts', 'context_only')
    ),
    evidence_quote TEXT NOT NULL,
    evidence_quote_sha256 TEXT NOT NULL,
    PRIMARY KEY (validation_report_id, evidence_id, evidence_quote_sha256)
);
```

원 검색 질의는 감사 목적으로 암호화 가능한 CAS 객체에 저장하고 일반 로그나 목록 API에서 노출하지 않는다. 실제 전송 질의만 정책이 허용한 경우 평문 필드에 저장한다.

### 5.8 승인과 산출물

```sql
CREATE TABLE approval_decision (
    approval_id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL CHECK (
        target_type IN ('validation_report', 'proposed_revision', 'artifact_generation')
    ),
    target_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected', 'deferred')),
    actor_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    decided_at TEXT NOT NULL,
    previous_approval_id TEXT REFERENCES approval_decision(approval_id) ON DELETE RESTRICT
);

CREATE INDEX ix_approval_target_time
ON approval_decision(target_type, target_id, decided_at DESC);

CREATE TABLE synthesis_artifact (
    artifact_id TEXT PRIMARY KEY,
    generation_id TEXT NOT NULL,
    topic_key TEXT NOT NULL,
    acl_policy_id TEXT NOT NULL REFERENCES acl_policy(acl_policy_id) ON DELETE RESTRICT,
    content_object_key TEXT NOT NULL REFERENCES stored_object(object_key) ON DELETE RESTRICT,
    content_sha256 TEXT NOT NULL,
    evidence_manifest_object_key TEXT NOT NULL REFERENCES stored_object(object_key) ON DELETE RESTRICT,
    evidence_manifest_sha256 TEXT NOT NULL,
    synthesis_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'draft', 'citation_failed', 'review_required',
            'approved', 'published'
        )
    ),
    created_at TEXT NOT NULL,
    published_at TEXT,
    UNIQUE (generation_id, topic_key, acl_policy_id)
);

CREATE TABLE artifact_claim (
    artifact_id TEXT NOT NULL REFERENCES synthesis_artifact(artifact_id) ON DELETE RESTRICT,
    claim_id TEXT NOT NULL REFERENCES claim(claim_id) ON DELETE RESTRICT,
    sentence_id TEXT NOT NULL,
    citation_ordinal INTEGER NOT NULL CHECK (citation_ordinal >= 0),
    PRIMARY KEY (artifact_id, sentence_id, claim_id, citation_ordinal)
);

CREATE TABLE artifact_generation (
    generation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    directory_path TEXT NOT NULL UNIQUE,
    manifest_sha256 TEXT NOT NULL,
    artifact_count INTEGER NOT NULL CHECK (artifact_count >= 0),
    status TEXT NOT NULL CHECK (
        status IN ('building', 'verified', 'approved', 'active', 'retired', 'failed')
    ),
    created_at TEXT NOT NULL,
    activated_at TEXT
);

CREATE UNIQUE INDEX ux_one_active_artifact_generation
ON artifact_generation(status)
WHERE status = 'active';
```

승인 결정은 덮어쓰지 않는다. 새 결정은 `previous_approval_id`로 기존 결정을 연결하며 현재 효력은 가장 최신 체인 말단으로 계산한다.

### 5.9 실행, 단계, 작업, 감사

사용자 문서 실행과 Worker 큐 작업은 별도 테이블이다. `document_job`은 GUI·CLI에 노출되는
장기 수명 주기이고 아래 `job` 테이블은 Worker가 소비하는 내부 큐다.

```sql
CREATE TABLE document_job (
    document_job_id TEXT PRIMARY KEY CHECK (document_job_id GLOB 'job-[0-9a-f]*'),
    state TEXT NOT NULL CHECK (state IN (
        'CREATED', 'INSPECTING', 'SNAPSHOTTING', 'EXTRACTING_EVIDENCE',
        'BUILDING_CLAIMS', 'PLANNING', 'RUNNING_TASKS', 'VALIDATING_TASKS',
        'ASSEMBLING', 'VALIDATING_FINAL', 'PUBLISHING', 'COMPLETED',
        'NEEDS_ATTENTION', 'CANCELLING', 'CANCELLED', 'FAILED'
    )),
    source_manifest_object_key TEXT REFERENCES stored_object(object_key) ON DELETE RESTRICT,
    pipeline_fingerprint TEXT NOT NULL,
    instruction_object_key TEXT NOT NULL REFERENCES stored_object(object_key) ON DELETE RESTRICT,
    artifact_root TEXT NOT NULL UNIQUE,
    last_event_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_event_sequence >= 0),
    last_percentage INTEGER NOT NULL DEFAULT 0 CHECK (last_percentage BETWEEN 0 AND 100),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE job_progress_event (
    document_job_id TEXT NOT NULL REFERENCES document_job(document_job_id) ON DELETE RESTRICT,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    stage TEXT NOT NULL,
    message TEXT NOT NULL,
    counter_name TEXT,
    completed INTEGER CHECK (completed IS NULL OR completed >= 0),
    total INTEGER CHECK (total IS NULL OR total >= 1),
    overall_percentage INTEGER CHECK (
        overall_percentage IS NULL OR overall_percentage BETWEEN 0 AND 100
    ),
    occurred_at TEXT NOT NULL,
    PRIMARY KEY (document_job_id, sequence),
    CHECK ((completed IS NULL) = (total IS NULL)),
    CHECK (completed IS NULL OR completed <= total)
);
```

```sql
CREATE TABLE pipeline_run (
    run_id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL CHECK (
        run_type IN ('benchmark', 'revision', 'ingestion', 'validation', 'synthesis', 'maintenance')
    ),
    pipeline_fingerprint TEXT NOT NULL,
    config_object_key TEXT NOT NULL REFERENCES stored_object(object_key) ON DELETE RESTRICT,
    code_version TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'running', 'cancelling', 'completed', 'failed', 'cancelled')
    ),
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    cancellation_requested_at TEXT
);

CREATE TABLE document_revision_run (
    revision_run_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE REFERENCES pipeline_run(run_id) ON DELETE RESTRICT,
    before_manifest_object_key TEXT NOT NULL REFERENCES stored_object(object_key) ON DELETE RESTRICT,
    before_manifest_sha256 TEXT NOT NULL,
    output_directory_path TEXT NOT NULL UNIQUE,
    comparison_object_key TEXT REFERENCES stored_object(object_key) ON DELETE RESTRICT,
    comparison_sha256 TEXT,
    state TEXT NOT NULL CHECK (state IN ('prepared', 'finalized', 'failed')),
    prepared_at TEXT NOT NULL,
    finalized_at TEXT,
    CHECK (
        (state = 'finalized' AND comparison_object_key IS NOT NULL AND comparison_sha256 IS NOT NULL AND finalized_at IS NOT NULL)
        OR state <> 'finalized'
    )
);

CREATE TABLE document_file_comparison (
    revision_run_id TEXT NOT NULL REFERENCES document_revision_run(revision_run_id) ON DELETE RESTRICT,
    relative_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('added', 'modified', 'removed', 'unchanged')),
    before_sha256 TEXT,
    after_sha256 TEXT,
    before_byte_count INTEGER CHECK (before_byte_count IS NULL OR before_byte_count >= 0),
    after_byte_count INTEGER CHECK (after_byte_count IS NULL OR after_byte_count >= 0),
    diff_object_key TEXT REFERENCES stored_object(object_key) ON DELETE RESTRICT,
    PRIMARY KEY (revision_run_id, relative_path),
    CHECK (before_sha256 IS NOT NULL OR after_sha256 IS NOT NULL)
);

CREATE TABLE stage_run (
    stage_run_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES pipeline_run(run_id) ON DELETE RESTRICT,
    stage_name TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (
        status IN (
            'pending', 'running', 'completed', 'failed',
            'quarantined', 'cancelled', 'skipped'
        )
    ),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    result_object_key TEXT REFERENCES stored_object(object_key) ON DELETE RESTRICT,
    result_sha256 TEXT,
    error_code TEXT,
    error_category TEXT,
    safe_error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE job (
    job_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES pipeline_run(run_id) ON DELETE RESTRICT,
    stage_run_id TEXT NOT NULL REFERENCES stage_run(stage_run_id) ON DELETE RESTRICT,
    job_type TEXT NOT NULL,
    priority INTEGER NOT NULL,
    payload_object_key TEXT NOT NULL REFERENCES stored_object(object_key) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (
        status IN (
            'pending', 'ready', 'running', 'retry_wait',
            'completed', 'failed', 'quarantined', 'cancelled'
        )
    ),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL CHECK (max_attempts >= 0),
    next_attempt_at TEXT,
    worker_id TEXT,
    lease_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX ix_job_ready_queue
ON job(status, next_attempt_at, priority DESC, created_at)
WHERE status IN ('ready', 'retry_wait');

CREATE TABLE audit_event (
    audit_event_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES pipeline_run(run_id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'system', 'worker')),
    actor_id TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    decision TEXT,
    reason_codes_json TEXT NOT NULL,
    context_json TEXT NOT NULL,
    previous_event_hash TEXT,
    event_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
```

`audit_event.event_hash`는 이전 이벤트 해시와 정규화 이벤트 JSON의 SHA-256이다. 로그 체인은 변조 방지 신호이며 전자서명을 대체하지 않는다.

## 6. 트랜잭션 경계

### 6.1 리비전 생성

하나의 트랜잭션에서 다음을 수행한다.

1. ACL policy upsert
2. document upsert와 `last_seen_at` 갱신
3. 동일 revision ID 조회
4. 새 `document_revision` 삽입
5. `pipeline_run`, `stage_run`, 첫 `job` 생성
6. 감사 이벤트 기록

CAS 원본 저장은 트랜잭션 전에 완료해야 한다. DB 커밋 실패 시 객체는 고아 정리 대상이 된다.

### 6.2 단계 완료

하나의 트랜잭션에서 다음을 수행한다.

1. 작업 리스와 worker ID 검증
2. 도메인 결과 행 삽입
3. `stage_run`을 `completed`로 compare-and-set
4. 현재 `job`을 `completed`로 변경
5. 후속 `stage_run`과 `job` 삽입
6. 감사 이벤트 기록

이미 완료된 idempotency key면 결과를 다시 쓰지 않고 기존 결과를 반환한다.

### 6.3 인덱스 활성화

1. 파일 세대 검증 완료
2. `BEGIN IMMEDIATE`
3. 기존 `active`를 `retired`로 변경
4. 새 `verified`를 `active`로 변경
5. 감사 이벤트 기록
6. commit

트랜잭션 실패 시 파일은 비활성 세대로 남고 기존 활성 세대를 계속 사용한다.

## 7. ACL 계산

### 7.1 Fingerprint

ACL fingerprint는 보안 등급과 정렬된 `(principal_type, principal_id, permission)` 목록의 정규 JSON SHA-256이다.

### 7.2 파생물 ACL

- 청크 ACL은 리비전 ACL과 동일하다.
- 중복 군집은 멤버별 ACL을 유지하며 정규본 ACL로 덮어쓰지 않는다.
- 검색 결과는 요청 주체가 읽을 수 있는 청크만 반환한다.
- 합성 입력은 동일 ACL fingerprint별로 먼저 분리한다.
- 여러 ACL을 병합해야 하는 경우 결과 ACL은 읽기 주체 교집합과 가장 높은 보안 등급이다.
- 교집합이 비면 합성을 거부한다.

## 8. FAISS 매니페스트

```json
{
  "schema_version": 1,
  "generation_id": "019...",
  "model_id": "BAAI/bge-m3",
  "model_revision": "pinned-revision",
  "dimension": 1024,
  "normalized": true,
  "metric": "inner_product",
  "index_type": "flat_ip",
  "vector_count": 100000,
  "index_sha256": "64-hex",
  "id_map_sha256": "64-hex",
  "created_at": "2026-08-10T06:00:00.000000Z"
}
```

`dimension`은 실제 고정 모델 descriptor에서 읽고 설정에 중복 하드코딩하지 않는다. 예제의 1024는 BGE-M3 dense 출력 검증 기대값이며 모델 리비전 변경 시 다시 검사한다.

## 9. 산출물 근거 매니페스트

각 게시 세대는 `evidence_manifest.jsonl`을 포함한다. 한 줄은 하나의 문장 또는 표 셀 근거다.

```json
{
  "schema_version": 1,
  "artifact_id": "sha256:...",
  "sentence_id": "s-000042",
  "sentence_sha256": "64-hex",
  "claim_ids": ["sha256:..."],
  "internal_sources": [
    {
      "revision_id": "sha256:...",
      "chunk_id": "sha256:...",
      "span_ordinal": 0,
      "quote_sha256": "64-hex"
    }
  ],
  "external_sources": [
    {
      "evidence_id": "sha256:...",
      "canonical_url": "https://example.com/release-notes",
      "retrieved_at": "2026-08-10T06:00:00.000000Z"
    }
  ]
}
```

문장 ID는 Markdown AST의 사실 문장과 표 셀에 결정적으로 부여한다. 제목, 순수 탐색 링크, 서식 요소는 근거 검사 대상에서 제외하되 제외 유형을 매니페스트에 기록한다.

## 10. 마이그레이션 정책

- 마이그레이션 파일은 순번, 이름, SHA-256 체크섬을 가진다.
- 시작 시 적용된 체크섬과 파일 체크섬이 다르면 쓰기 모드 시작을 거부한다.
- 스키마 변경 전 SQLite 온라인 백업과 현재 인덱스·산출물 매니페스트를 저장한다.
- additive 변경을 우선하고 destructive 변경은 복사 테이블 방식으로 수행한다.
- 마이그레이션 중 모델 워커를 시작하지 않는다.
- 실패 시 DB 백업을 복원하고 파일 세대는 기존 활성 포인터를 유지한다.
- downgrade 자동화는 제공하지 않고 이전 전체 백업 복원으로 처리한다.

## 11. 보존과 정리

| 데이터 | 기본 보존 | 삭제 조건 |
| --- | --- | --- |
| 원본 리비전 | 무기한 | 승인된 별도 데이터 보존 정책 필요 |
| `data/before` 스냅샷 | 데이터 관리자 정책 | 활성·감사 run이 참조하는 동안 삭제 금지 |
| finalized after run | 최근 10개 이상 | 승인·감사·게시 참조 제외 불가 |
| 정규화 객체 | 원본과 동일 | 재생성 가능해도 기본 보존 |
| 비활성 FAISS 세대 | 최근 3개 | 활성·롤백 세대 제외 |
| 비활성 산출물 세대 | 최근 10개 | 승인·감사 참조 제외 |
| 실패 staging | 7일 | 실행 종료와 비참조 확인 |
| 애플리케이션 로그 | 30일 | 회전 정책 |
| 감사 로그 | 조직 정책 | 보안 승인 필요 |
| 외부 근거 스냅샷 | 최소 1년 | 게시 근거 참조 제외 불가 |

정리는 dry-run 매니페스트를 먼저 생성하고 참조 무결성을 검사한 뒤 수행한다.

## 12. 백업·복구 무결성

백업 세트는 다음을 동일 backup ID로 묶는다.

1. SQLite 일관 백업
2. SQLite 백업 SHA-256
3. 활성 FAISS 세대 전체
4. 활성 산출물 세대 전체
5. DB가 참조하는 CAS 객체 목록
6. 설정 스냅샷과 파이프라인 지문
7. backup manifest와 전체 체크섬
8. 활성 입력 매니페스트와 finalized after run 비교 보고서

복구는 격리 디렉터리에서 체크섬, SQLite foreign key, object reference, FAISS 벡터 수, 산출물 근거 매니페스트를 검증한 뒤 활성 경로를 교체한다.

## 13. 데이터 모델 테스트

- 모든 foreign key와 CHECK 제약 위반 시험
- 결정적 ID의 순서·유니코드 정규화 속성 시험
- ACL 변경 시 새 리비전 생성 시험
- 단계 완료와 후속 작업 원자성 시험
- 동일 idempotency key 중복 커밋 방지 시험
- 워커 리스 만료와 작업 회수 시험
- 활성 인덱스·산출물 유일성 시험
- 승인 append-only 체인 시험
- CAS 객체 누락과 해시 불일치 탐지 시험
- backup manifest 기반 빈 호스트 복구 시험
- before 해시 변화 탐지와 finalized run 쓰기 거부 시험
- file comparison 상태·NULL 조합 CHECK 제약 시험
