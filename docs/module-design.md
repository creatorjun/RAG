<!-- docs/module-design.md -->
# 아키텍처 모듈 상세 설계

## 1. 설계 규약

- Python 3.12의 `dataclass(frozen=True, slots=True)`, `Enum`, `Protocol`을 기본 도구로 사용한다.
- 도메인 객체는 I/O를 수행하지 않고 생성 시 불변 조건을 검증한다.
- 날짜는 UTC timezone-aware `datetime`만 허용한다.
- 경로는 인프라 경계에서만 `Path`를 사용하고 도메인에는 URI 또는 저장소 키를 전달한다.
- 외부 라이브러리 타입은 어댑터 밖으로 노출하지 않는다.
- 공개 DTO와 워커 메시지는 명시적 `schema_version`을 가진다.
- `None`은 의미가 명확한 선택 필드에만 사용하고 상태 표현에는 Enum을 사용한다.
- 정상적인 업무 분기는 예외가 아니라 결과 Enum으로 표현한다.
- 인프라 실패는 분류 가능한 애플리케이션 예외로 변환한다.

## 2. Domain 계층

### 2.1 엔터티

#### `Document`

| 필드 | 타입 | 규칙 |
| --- | --- | --- |
| `document_id` | `DocumentId` | 소스 내 논리 문서의 안정 ID |
| `source_id` | `SourceId` | 등록된 소스 참조 |
| `external_key` | `str` | 소스가 제공한 변경 불가 식별자 |
| `created_at` | `datetime` | 최초 발견 시각 |
| `status` | `DocumentStatus` | `ACTIVE`, `DELETED_AT_SOURCE`, `DISABLED` |

`Document`는 내용을 소유하지 않는다. 내용과 메타데이터 스냅샷은 `DocumentRevision`에만 저장한다.

#### `DocumentRevision`

| 필드 | 타입 | 규칙 |
| --- | --- | --- |
| `revision_id` | `RevisionId` | 결정적 ID |
| `document_id` | `DocumentId` | 부모 문서 |
| `source_version` | `str` | 소스 버전, 없으면 해시 기반 값 |
| `content_sha256` | `Sha256` | 원본 바이트 해시 |
| `raw_object_key` | `ObjectKey` | CAS 객체 참조 |
| `mime_type` | `MimeType` | 검사된 MIME |
| `title` | `str` | 빈 문자열 금지 |
| `source_modified_at` | `datetime | None` | 소스가 제공할 때만 사용 |
| `captured_at` | `datetime` | 수집 완료 시각 |
| `security_label` | `SecurityLabel` | 보안 등급 |
| `acl` | `AclSet` | 최소 한 개의 허용 주체 또는 명시적 운영자 전용 |
| `metadata` | `Mapping[str, JsonScalar]` | 허용 키만 정규화 |

불변 조건은 원본 객체의 해시가 `content_sha256`과 일치하고, 동일 `revision_id`가 다른 콘텐츠를 가리키지 않는 것이다.

#### `Chunk`

| 필드 | 타입 | 규칙 |
| --- | --- | --- |
| `chunk_id` | `ChunkId` | 결정적 ID |
| `revision_id` | `RevisionId` | 정확히 하나의 리비전 |
| `ordinal` | `int` | 0 이상, 리비전 내 유일 |
| `display_text` | `str` | 원문 표현과 인용에 사용 |
| `embedding_text` | `str` | 제목 경로를 포함한 임베딩 입력 |
| `token_count` | `int` | 1 이상, 설정 최대 이하 |
| `content_sha256` | `Sha256` | 정규화된 `display_text` 해시 |
| `heading_path` | `tuple[str, ...]` | 문서 구조 경로 |
| `source_spans` | `tuple[SourceSpan, ...]` | 비어 있을 수 없음 |
| `parent_chunk_id` | `ChunkId | None` | 계층 청크일 때만 사용 |
| `previous_chunk_id` | `ChunkId | None` | 같은 리비전 내 인접 청크 |
| `next_chunk_id` | `ChunkId | None` | 같은 리비전 내 인접 청크 |

#### `DuplicateCluster`

| 필드 | 타입 | 규칙 |
| --- | --- | --- |
| `cluster_id` | `DuplicateClusterId` | 군집 버전과 멤버 집합 기반 |
| `generation_id` | `DedupGenerationId` | 판정 설정 세대 |
| `canonical_chunk_id` | `ChunkId` | 멤버 중 하나 |
| `members` | `tuple[DuplicateMember, ...]` | 2개 이상 |
| `status` | `DuplicateStatus` | `CONFIRMED`, `REVIEW_REQUIRED`, `CONFLICT` |
| `reason` | `CanonicalReason` | 선정 우선순위 근거 |

군집은 삭제 명령을 만들지 않는다. 검색 시 정규본 가중치와 멤버 계보만 제공한다.

#### `Claim`

| 필드 | 타입 | 규칙 |
| --- | --- | --- |
| `claim_id` | `ClaimId` | 정규화 주장과 출처 기반 |
| `subject` | `str` | 빈 값 금지 |
| `predicate` | `str` | 허용 predicate 또는 `other` |
| `object` | `str` | 빈 값 금지 |
| `claim_type` | `ClaimType` | 7개 고정 유형 |
| `source_refs` | `tuple[ClaimSourceRef, ...]` | 하나 이상 |
| `external_verifiability` | `RiskLevel` | `LOW`, `MEDIUM`, `HIGH` |
| `freshness_risk` | `RiskLevel` | `LOW`, `MEDIUM`, `HIGH` |
| `confidence` | `Probability` | 0 이상 1 이하 |
| `extraction_run_id` | `RunId` | 생성 실행 참조 |

#### `ExternalEvidence`

| 필드 | 타입 | 규칙 |
| --- | --- | --- |
| `evidence_id` | `EvidenceId` | 정규 URL과 본문 해시 기반 |
| `canonical_url` | `HttpsUrl` | HTTPS 공개 주소 |
| `publisher` | `str` | 발행 주체 |
| `title` | `str` | 빈 값 금지 |
| `published_at` | `datetime | None` | 추정 금지 |
| `retrieved_at` | `datetime` | UTC |
| `content_sha256` | `Sha256` | 저장 본문 해시 |
| `object_key` | `ObjectKey` | CAS 스냅샷 |
| `trust_tier` | `TrustTier` | `PRIMARY`, `AUTHORITATIVE`, `SECONDARY`, `UNKNOWN` |
| `content_type` | `str` | 허용된 텍스트 유형 |

#### `ValidationReport`

- `relation`은 `CONFIRMED`, `OUTDATED`, `CONTRADICTED`, `NOT_APPLICABLE`, `INSUFFICIENT_EVIDENCE` 중 하나다.
- `internal_current_state`, `external_public_state`, `proposed_change`를 분리한다.
- `evidence_ids`는 `OUTDATED`, `CONTRADICTED`, `CONFIRMED`에서 하나 이상이어야 한다.
- `INSUFFICIENT_EVIDENCE`는 모델 배경지식으로 상태를 채우지 않는다.

#### `SynthesisArtifact`

- 하나의 `topic_key`와 하나의 ACL fingerprint를 가진다.
- `content`의 모든 사실 문장에는 `CitationRef`가 연결된다.
- `status`는 `DRAFT`, `CITATION_FAILED`, `REVIEW_REQUIRED`, `APPROVED`, `PUBLISHED`다.
- `PUBLISHED` 상태는 변경 불가이며 새 버전은 새 artifact ID를 사용한다.

#### `DocumentJob`

- `job_id`, `state`, 입력 스냅샷 ID, 파이프라인 지문
- 허용된 상태 전이와 terminal 상태 불변 조건
- 진행 이벤트의 마지막 sequence와 단조 증가 percentage

#### `ClaimLedger`

- Evidence에 연결된 원자 Claim 집합
- 중복·보완·의도적 반복·충돌 관계
- Derived-only Claim 게시 금지

#### `CoverageMatrix`

- 필수 Claim과 원본 구조 요소의 Task·최종 섹션 배정
- 계획 확정 후 전체 작업량 불변
- 미배정 필수 요소가 있으면 실행 계획 확정 금지

### 2.2 Value Objects

| 값 객체 | 핵심 검증 |
| --- | --- |
| `Sha256` | 소문자 64자리 16진수 |
| `Probability` | 유한 실수, 0~1 |
| `SourceSpan` | 페이지·섹션·문단·오프셋 중 최소 하나 존재 |
| `SecurityLabel` | `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `RESTRICTED` |
| `AclSet` | 정규화·정렬된 주체 집합, 교집합 연산 제공 |
| `PipelineFingerprint` | SHA-256과 구성요소 매니페스트 |
| `TokenBudget` | 입력·출력·예약 토큰 합계가 컨텍스트 이하 |
| `NormalizedUrl` | HTTPS, fragment 제거, IDN 정규화, 금지 IP 미포함 |
| `IdempotencyKey` | 단계, 대상 ID, 파이프라인 지문의 결정적 결합 |

### 2.3 Domain Policies

#### `ClassificationPolicy`

입력은 메타데이터 점수, 규칙 점수, 기술 중심점 유사도, 비기술 중심점 유사도, 문서 집계 점수다. 출력은 `ClassificationDecision`이다. 정책은 모델 호출이나 DB 조회를 수행하지 않는다.

#### `CanonicalizationPolicy`

정규본 선정 순서는 정본 소스, 승인, 소스 버전 신뢰도, 수정 시각, 구조 품질, 결정적 ID 순이다. 수정 시각 비교는 둘 다 존재하고 소스 신뢰도가 같을 때만 사용한다.

#### `WebEgressPolicy`

검색 활성화, 주장 유형, 검증 가능성, 최신성 위험, 보안 등급, 민감 패턴, 도메인 정책을 평가해 `ALLOW`, `BLOCK`, `REVIEW`를 반환한다. 정책 자체는 네트워크를 호출하지 않는다.

#### `SynthesisPolicy`

승인 상태, ACL 교집합, 근거 신뢰도, 충돌 상태를 검사해 근거 카드 포함 여부를 결정한다. 충돌 주장은 일반 사실 섹션에 포함하지 않고 충돌 섹션으로 라우팅한다.

## 3. Application 계층

### 3.1 유스케이스

| 유스케이스 | 입력 DTO | 출력 DTO | 트랜잭션 경계 |
| --- | --- | --- | --- |
| `InventoryDocuments` | 소스 ID, cursor, 범위 | 발견·변경·삭제 후보 | 후보 배치 커밋 |
| `IngestDocument` | 후보 ID | 리비전 ID, 생성 작업 | 리비전과 작업 원자 커밋 |
| `NormalizeDocument` | 리비전 ID | 정규화 매니페스트 | 객체 저장 후 메타 커밋 |
| `CreateChunks` | 정규화 ID | 청크 ID 목록 | 리비전 단위 |
| `ClassifyChunks` | 리비전 ID, 정책 버전 | 판정 요약 | 리비전 단위 |
| `EmbedChunks` | 청크 ID 배치, 모델 리비전 | 임베딩 레코드 | 배치 단위 |
| `DeduplicateChunks` | 세대 ID, 청크 범위 | 군집·충돌 | 세대 단위 |
| `ActivateVectorGeneration` | 세대 ID | 활성 세대 | 포인터 원자 변경 |
| `ExtractClaims` | 청크 번들 ID | 주장 ID 목록 | 번들 단위 |
| `PlanWebValidation` | 주장 ID | 질의 결정 목록 | 주장 단위 |
| `CollectExternalEvidence` | 허용 질의 ID | 근거 또는 차단 결과 | 질의 단위 |
| `ValidateClaims` | 주장·근거 ID | 검증 보고서 | 주장 단위 |
| `RecordApproval` | 대상, 결정, 행위자 | 승인 ID | 단일 결정 |
| `SynthesizeTopic` | 주제, ACL fingerprint | 초안 artifact ID | 주제 단위 |
| `PublishArtifacts` | artifact 세대 | 게시 매니페스트 | 세대 활성화 |
| `CreateDocumentJob` | source root, 작업 지시 | DocumentJob | Job 생성 |
| `InspectDocumentJob` | Job ID | source manifest | Job checkpoint |
| `PlanDocumentTasks` | Claim Ledger, 요구사항 | Coverage Matrix, TaskPacket | 계획 확정 |
| `ExecuteDocumentTask` | TaskPacket | TaskOutput | Task attempt |
| `ValidateDocumentTask` | TaskPacket, TaskOutput | 검증 보고서 | Task attempt |
| `AssembleDocument` | 검증된 TaskOutput | Markdown 후보 | Job artifact |
| `PublishDocumentJob` | 품질 게이트 통과 Job | revision run | after run 생성·비교 |

### 3.2 애플리케이션 서비스

#### `PipelineOrchestrator`

- 실행 생성과 설정 스냅샷 고정
- 단계 DAG 생성
- 준비된 작업을 리소스 스케줄러에 제출
- 단계 결과 커밋 후 후속 작업 생성
- 취소 전파와 실행 종료 판정

비즈니스 알고리즘을 직접 구현하지 않고 유스케이스와 포트를 조정한다.

대화 기록을 상태로 사용하지 않으며 JobRepository, ArtifactRepository, ProgressEventPublisher를
통해 모든 체크포인트를 명시적으로 저장한다. 품질 게이트 전 FolderRevisionWorkspace 호출을
금지한다.

#### `TaskPlanner`

- Claim Ledger와 요구사항에서 Coverage Matrix 생성
- 고정 Task DAG와 TaskPacket 생성
- 원본 구조 요소 100% 배정 검증

#### `DeterministicDocumentAssembler`

- 검증된 Task 섹션만 입력 허용
- 제목, 목차, 번호, 출처, 원본 목록을 결정적으로 렌더링
- 전체 문서 모델 재작성 호출 금지

#### `ResourceScheduler`

- 리스 요청 우선순위 큐
- 상호 배타 리스 검사
- 워커 프로세스 생명 주기
- 메모리 상태와 배치 축소 결정
- 만료 리스와 비정상 워커 회수

#### `CheckpointManager`

- 멱등성 키 조회
- 단계 시작 compare-and-set
- 결과 매니페스트와 후속 작업 원자 커밋
- 재시도 횟수와 다음 실행 시각 계산
- 고아 `RUNNING` 작업 회수

## 4. Infrastructure 계층

### 4.1 소스 어댑터

#### `FilesystemDocumentSource`

- 승인된 절대 루트 아래의 파일만 열기
- 심볼릭 링크는 기본 거부
- 확장자, MIME, magic bytes 교차 검사
- 안정된 파일 읽기를 위해 크기와 수정 시각을 읽기 전후 비교
- 변경 중 파일은 `SOURCE_BUSY`로 재시도
- 원본 스냅샷은 스트리밍 SHA-256과 동시에 CAS 임시 객체에 저장

#### `BeforeFolderDocumentSource`

- 해석된 `data/before` 절대 경로만 source root로 허용
- 파일 상대 경로를 `external_key`로 사용하고 콘텐츠 해시를 source version에 포함
- 승인된 sidecar의 문서 ID, 버전, 수정 시각, 작성자, 보안 등급을 스냅샷
- sidecar가 없으면 가장 제한적인 기본 ACL과 파일 메타데이터를 사용
- 심볼릭 링크, junction, 특수 파일, 경로 탈출을 거부
- 원본 시스템 API와 자격정보를 전혀 사용하지 않음

### 4.2 파서 어댑터

모든 파서는 `NormalizedDocument`를 반환하며 공통 요소 유형 `HEADING`, `PARAGRAPH`, `LIST_ITEM`, `TABLE`, `CODE_BLOCK`, `IMAGE_CAPTION`, `PAGE_BREAK`를 사용한다.

| 어댑터 | 우선 구현 | 실패 처리 |
| --- | --- | --- |
| `PdfParser` | 텍스트 레이어, 페이지·블록 좌표 | 손상·암호화 격리 |
| `DocxParser` | 제목, 문단, 표, 목록 | 관계 손상 격리 |
| `HtmlParser` | 본문, 제목, 표, 코드 | 스크립트·스타일 제거 |
| `MarkdownParser` | AST 기반 구조 보존 | 유효하지 않은 구문도 텍스트 보존 |
| `OcrParser` | 텍스트 밀도 낮은 PDF 페이지만 | 페이지 단위 실패 표시 |

### 4.3 모델 어댑터

#### `BgeM3Embedder`

- 모델 ID와 리비전을 명시적으로 고정
- 첫 버전은 dense 벡터를 필수 반환
- 출력 벡터를 L2 정규화
- 입력 순서와 출력 순서 일치 검증
- NaN, Inf, 차원 불일치 시 배치 전체 실패
- OOM 시 배치를 절반으로 나누어 최소 1까지 재시도

#### `MlxQwenClient`

- `mlx-community/Qwen3.6-27B-4bit` 고정 리비전 사용
- 텍스트 작업은 비전 입력 없이 호출
- 입력 토큰, 예약 출력, 시스템 프롬프트를 합산해 예산 검사
- 스트리밍 조각은 워커 내부에서 조립 후 JSON 스키마 검증
- 구조 출력 실패 시 같은 근거로 교정 프롬프트 1회 허용
- 교정 실패는 `ModelOutputValidationError`

### 4.4 저장 어댑터

#### `SqliteMetadataRepository`

- WAL 모드, foreign key 활성화, busy timeout 설정
- Coordinator만 쓰기 연결 소유
- 읽기 연결은 read-only URI 사용
- 스키마 버전 불일치 시 자동 파괴적 마이그레이션 금지
- 도메인 객체와 행 매핑을 별도 mapper에 격리

#### `FaissVectorIndex`

- cosine 검색을 위해 정규화 벡터와 inner product 인덱스 사용
- 인덱스 파일, ID 맵, 매니페스트를 동일 세대 디렉터리에 저장
- 읽기 시 파일 해시와 벡터 수 검증
- 활성 세대 변경 전에 smoke query 실행
- 삭제는 tombstone과 다음 세대 재빌드로 반영

#### `FilesystemArtifactRepository`

- 콘텐츠 주소 저장과 실행별 임시 디렉터리 분리
- fsync 후 같은 볼륨에서 rename으로 활성화
- 활성 매니페스트가 참조하는 파일은 보존 정책에서 제외
- 해시가 같은 객체는 중복 저장하지 않음

#### `FolderRevisionWorkspace`

- 고유 run ID로 `data/after/runs/<run_id>`만 신규 생성
- before 트리를 `documents`에 복사하면서 전후 SHA-256 일치 검증
- 기존 run 충돌 시 덮어쓰지 않고 `RUN_ALREADY_EXISTS`
- finalization 전 현재 run의 `documents`만 쓰기 허용
- finalization 후 새 run을 요구

#### `FolderTreeComparator`

- before와 current run documents를 상대 경로로 정렬 비교
- added, modified, removed, unchanged 상태와 전후 해시 기록
- UTF-8 텍스트는 unified diff를 만들고 binary는 해시와 크기만 기록
- `_reports`를 비교 입력에서 제외하고 원자적으로 보고서 교체

### 4.5 보안 어댑터

#### `MacOsKeychainStore`

- 선택적 공개 웹 검색의 서비스명과 계정명으로 비밀 조회
- 비밀 문자열을 로그 또는 예외 메시지에 포함하지 않음
- 키 존재 여부와 실제 값 조회를 분리
- 모델 워커와 문서 리비전 스킬에는 자격정보를 전달하지 않음
- Confluence 자격정보 항목을 정의하거나 조회하지 않음

## 5. Presentation 계층

### 5.1 CLI 명령 집합

| 명령 | 역할 | 기본 부작용 |
| --- | --- | --- |
| `rag source add` | 승인 소스 등록 | 설정 DB 변경 |
| `rag source list` | 등록 소스와 활성 상태 조회 | 없음 |
| `rag revision prepare` | 신규 before/after run 준비 | 새 run과 입력 매니페스트 생성 |
| `rag revision compare` | 현재 run의 파일별 비교 | `_reports` 생성·갱신 |
| `rag revision finalize` | 비교 검증 후 run 고정 | finalization 기록 |
| `rag ingest` | 증분 실행 생성 | 작업 큐 생성 |
| `rag validate` | 인제스천 실행의 검증 작업 생성 | 작업 큐 생성 |
| `rag run status` | 실행과 단계 상태 조회 | 없음 |
| `rag job create` | 원본 폴더와 작업 지시로 Job 생성 | Job ID |
| `rag job run` | 계획된 Job 실행 또는 재개 | 진행 이벤트 |
| `rag job cancel` | 안전 취소 요청 | Job 상태 |
| `rag run cancel` | 실행 취소 요청 | 취소 플래그 설정 |
| `rag review list` | 승인 대기 목록 | 없음 |
| `rag review decide` | 승인 결정 기록 | 승인 레코드 추가 |
| `rag synthesize` | 주제 합성 실행 | 작업 큐 생성 |
| `rag publish` | 검증된 세대 게시 | 활성 산출물 변경 |
| `rag benchmark` | 모델·메모리 벤치마크 | 벤치마크 파일 생성 |
| `rag doctor` | 설치·저장소·모델 점검 | 기본 읽기 전용 |
| `rag serve` | Coordinator와 선택 API 시작 | 장기 실행 프로세스 시작 |
| `rag shutdown` | Coordinator 안전 종료 요청 | 실행 작업 취소와 리소스 종료 |

### 5.2 API 원칙

- API는 선택 기능이며 CLI와 같은 유스케이스를 호출한다.
- 기본 listen 주소는 `127.0.0.1`이다.
- 장시간 작업은 동기 HTTP 응답으로 기다리지 않고 `run_id`를 반환한다.
- 원문 조회 API는 기본 제공하지 않는다.
- 오류 응답은 내부 경로, 원문, 비밀값을 포함하지 않는다.

### 5.3 로컬 GUI

`presentation/gui`는 PySide6 View와 ViewModel만 포함한다. 폴더 선택, Job 생성, 진행 이벤트
조회, 결과 열기, 완료 알림을 제공하며 파일 시스템·SQLite·MLX를 직접 호출하지 않는다.
GUI와 CLI는 같은 Application 유스케이스를 사용한다.

## 6. Bootstrap과 의존성 조립

부트스트랩 순서는 고정한다.

1. 설정 파일 로드와 스키마 검증
2. 웹 활성 시에만 외부 검색 비밀 참조 유효성 검사
3. before 읽기 전용, after 신규 run 쓰기, 경로 비중첩 검사
4. SQLite 스키마 버전 검사
5. 저장소와 CAS 어댑터 생성
6. disabled 또는 Tavily 검색 어댑터 선택
7. 리소스 스케줄러와 워커 팩토리 생성
8. 유스케이스 생성
9. CLI 또는 API 프레젠테이션 시작

부트스트랩 실패는 어떤 워커도 생성하기 전에 종료한다. 부분 생성된 리소스는 생성 역순으로 닫는다.

## 7. 모듈 완료 기준

- 각 도메인 엔터티의 불변 조건 단위 테스트
- 각 포트의 fake 어댑터와 계약 테스트
- 각 프로덕션 어댑터의 정상·경계·실패 통합 테스트
- 계층 의존성 위반 0건
- import 시 I/O 발생 0건
- 워커 종료 후 모델 프로세스 잔존 0개
- 모든 공개 Enum과 DTO가 문서·스키마·코드에서 동일
#### `FilesystemJobArtifactRepository`

- `var/jobs/<job_id>`를 staging에서 원자적으로 초기화
- JSON checkpoint는 write-once이며 기존 파일 덮어쓰기 금지
- 상대 `.json` 경로만 허용하고 link·경로 탈출 차단
- Job 상태 변경은 이 저장소가 아니라 DocumentJobRepository가 담당
