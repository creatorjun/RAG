<!-- docs/configuration.md -->
# 설정 스키마와 버전 관리

## 1. 원칙

- 모든 실행은 병합 완료된 설정 스냅샷을 CAS에 저장한다.
- 실행 중 설정 파일 변경은 현재 실행에 반영하지 않는다.
- Confluence 자격정보는 설정 스키마 자체에 존재하지 않는다.
- 선택적 공개 웹 검색 비밀만 설정 파일 대신 Keychain 참조로 저장한다.
- 환경별 설정은 값만 바꾸며 스키마와 의미를 바꾸지 않는다.
- 품질 임계값이 `null`이면 해당 자동 판정을 활성화하지 않는다.
- 알 수 없는 키는 경고가 아니라 시작 오류다.
- 경로는 부트스트랩에서 절대 경로로 정규화하고 승인 루트 밖으로 벗어날 수 없다.

## 2. 설정 우선순위

낮은 우선순위부터 다음 순서로 병합한다.

1. 코드 내 스키마 기본값
2. `config/default.yaml`
3. `config/<environment>.yaml`
4. 허용된 `RAG_` 환경 변수
5. CLI의 명시적 일회성 override

비밀값은 병합 대상이 아니며 웹 검색이 활성화된 경우에만 `secret_ref`를 통해 Coordinator가 조회한다. 문서 폴더 스킬과 모델 워커는 비밀 참조를 받을 수 없다. CLI override는 벤치마크와 운영자가 승인한 제한 항목에만 허용한다.

### 2.1 GUI 사용자 설정과 실행 스냅샷

환경 YAML은 배포·보안 상한이고 GUI가 저장하는 `var/config/desktop-settings.json`은 다음 Job의
사용자 기본값이다. GUI 설정은 허용된 폴더, 모델, 추가 프롬프트와 실행 정책만 변경할 수 있으며
web egress, Evidence 제한, 품질 게이트, 경로 보안 플래그를 덮어쓸 수 없다.

```text
운영 YAML 상한
→ GUI 사용자 기본값
→ Job 생성 시 유효성 검사·모델 revision 해석
→ immutable Job settings snapshot
```

GUI 설정은 `settings_revision` compare-and-set으로 저장한다. 실행 중 설정 변경은 새 Job에만
적용된다. 모델의 branch/tag 또는 `latest` 표시는 Job 생성 전에 정확한 Hugging Face commit
revision과 파일 hash로 해석하며 해석되지 않은 모델로 Job을 시작하지 않는다.

사용자 추가 시스템 지침은 고정 보안·Evidence 정책 뒤에만 합성한다. 빈 값과 최대 20,000자를
허용하되 고정 정책을 대체하거나 도구·네트워크·Evidence 권한을 확장하지 못한다. 결합된 prompt의
정규 hash를 Job snapshot에 기록한다.

`offline_mode=true`인 Job Worker는 Hugging Face에 요청하지 않고 고정된 model ID·commit을
로컬 cache에서만 해석한다. cache miss는 암묵적 다운로드가 아니라 `MODEL_NOT_CACHED`로
실패한다. 다운로드를 허용할 때만 새 Job 설정에서 오프라인 모드를 해제한다.

설정 탭의 `최신 모델 검색`도 `offline_mode=false`일 때 사용자가 명시적으로 눌러야만
`mlx-community` 공개 카탈로그에 접근한다. 검색 결과의 branch/tag는 Job에 저장하지 않고 응답의
정확한 40자리 commit을 사용한다. `offline_mode=false`는 자동 다운로드 동의가 아니며, 현재
구현에서는 별도 다운로드 단계가 완료되기 전까지 조회·선택·검증만 제공하며, cache되지 않은
원격 모델의 Job 생성과 Worker의 숨은 자동 다운로드를 차단한다.

## 3. 전체 설정 기준안

```yaml
schema_version: 1
environment: development

paths:
  before_root: "./data/before"
  after_root: "./data/after"
  var_root: "./var"
  database: "./var/database/metadata.sqlite3"
  object_store: "./var/objects"
  vector_indexes: "./var/indexes/vectors"
  artifact_generations: "./var/artifacts/generations"
  staging: "./var/staging"
  quarantine: "./var/quarantine"
  logs: "./var/logs"

runtime:
  python: "3.12"
  checkpoint_enabled: true
  worker_start_timeout_seconds: 30
  worker_heartbeat_seconds: 5
  worker_missed_heartbeats: 3
  cancellation_grace_seconds: 15
  track_a_idle_shutdown_seconds: 60
  track_b_idle_shutdown_seconds: 120
  max_parallel_llm_jobs: 1
  parse_concurrency: 2
  ocr_concurrency: 1
  network_concurrency: 2

memory:
  sample_interval_seconds: 5
  pressure_available_gib: 6
  critical_available_gib: 3
  recovery_available_gib: 8
  healthy_samples_to_recover: 3
  swap_growth_mib_per_minute: 512

sources:
  max_file_bytes: 2147483648
  inventory_page_size: 100
  reject_symlinks: true
  allowed_roots:
    - "./data/before"

document_workspace:
  run_id_pattern: "^[a-z0-9][a-z0-9._-]{1,62}[a-z0-9]$"
  preserve_relative_paths: true
  reject_symlinks: true
  reject_junctions: true
  never_overwrite_run: true
  require_input_manifest: true
  require_comparison_report: true
  finalize_immutable: true

parsing:
  parser_version: "1"
  allowed_mime_types:
    - "application/pdf"
    - "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    - "text/html"
    - "text/markdown"
    - "text/plain"
  pdf:
    ocr_enabled: true
    ocr_min_characters_per_page: 80
    ocr_min_valid_character_ratio: 0.60
    max_pages: 10000
  html:
    remove_scripts: true
    remove_styles: true
    max_dom_nodes: 1000000

normalization:
  version: "1"
  unicode_form: "NFC"
  newline: "LF"
  preserve_code_whitespace: true
  preserve_table_coordinates: true

chunking:
  version: "1"
  tokenizer_id: "Qwen/Qwen3.6-27B"
  tokenizer_revision: "pinned-revision"
  target_tokens: 800
  max_tokens: 1200
  minimum_tokens: 80
  overlap_ratio: 0.12
  max_heading_prefix_tokens: 120
  preserve_tables: true
  preserve_code_blocks: true

models:
  llm:
    backend: "mlx-lm"
    model_id: "mlx-community/Qwen3.6-27B-4bit"
    revision: "c000ac2c2057d94be3fa931000c31723aac53282"
    context_tokens: 16384
    reserved_tokens: 512
  embedding:
    id: "BAAI/bge-m3"
    revision: "pinned-revision"
    batch_size: 8
    min_batch_size: 1
    max_input_tokens: 1200
    use_fp16: true
    normalize: true

classification:
  policy_version: "1"
  labeled_dataset_version: "unconfigured"
  technical_threshold: null
  non_technical_threshold: null
  metadata_weight: 0.20
  rule_weight: 0.20
  semantic_weight: 0.60
  uncertain_review: true

deduplication:
  version: "1"
  minhash_ngram: 5
  minhash_permutations: 128
  near_text_threshold: null
  semantic_threshold: null
  semantic_review_lower_bound: null
  faiss_candidate_count: 20
  retain_all_revisions: true

vector_index:
  initial_type: "flat_ip"
  hnsw_transition_vector_count: 500000
  hnsw_transition_p95_ms: 250
  smoke_query_count: 100
  retained_generations: 3

claims:
  extraction_prompt_version: "1"
  validation_prompt_version: "1"
  extraction_max_output_tokens: 2048
  validation_max_output_tokens: 2048
  structured_repair_attempts: 1

web:
  enabled: false
  provider: "disabled"
  secret_ref: null
  policy_version: "1"
  allow_private_content: false
  allowed_domains: []
  maximum_results: 5
  connect_timeout_seconds: 5
  total_timeout_seconds: 20
  maximum_redirects: 3
  maximum_response_bytes: 5242880
  allowed_content_types:
    - "text/html"
    - "text/plain"
    - "application/pdf"

synthesis:
  map_prompt_version: "1"
  reduce_prompt_version: "1"
  map_max_output_tokens: 4096
  reduce_max_output_tokens: 4096
  final_max_output_tokens: 8192
  input_budget_ratio: 0.80
  taxonomy_version: "1"

publishing:
  require_approval: true
  require_citations: true
  required_evidence_coverage: 1.0
  retained_generations: 10

jobs:
  source_busy_attempts: 3
  network_attempts: 3
  resource_pressure_attempts: 3
  internal_error_attempts: 1

logging:
  level: "INFO"
  format: "jsonl"
  include_source_text: false
  include_model_output: false
  maximum_file_bytes: 104857600
  retained_files: 30

backup:
  root: "./var/backups"
  verify_after_create: true
```

`pinned-revision`과 `unconfigured`는 개발 시작 시 기술 스파이크 산출물로 교체해야 하며 production 환경 검증에서 허용하지 않는다.

## 4. 필드 유효성 규칙

### 4.1 경로

- 모든 write path는 `var_root` 아래여야 한다.
- 예외적으로 게시 write path인 `after_root`만 `var_root` 밖에서 허용한다.
- source `allowed_roots`는 정확히 `before_root`만 포함하고 `var_root`, `after_root`와 겹치지 않아야 한다.
- `before_root`에는 쓰기·삭제·이동 권한이 없어야 하고 `after_root`에는 신규 run 생성 권한만 필요하다.
- run ID와 문서 상대 경로는 정규화 후 `after_root/runs/<run_id>`를 벗어날 수 없다.
- object store, database, vector index, artifact, staging, quarantine는 서로 중첩하지 않는다.
- 심볼릭 링크 해석 후에도 동일 조건을 검사한다.

### 4.2 런타임과 메모리

- `max_parallel_llm_jobs`는 대상 장비에서 1만 허용한다.
- `worker_heartbeat_seconds * worker_missed_heartbeats`는
  `worker_start_timeout_seconds`보다 작아야 한다. 현재 기본값은 15초와 30초다.
- `critical < pressure < recovery`를 만족해야 한다.
- batch minimum은 1이고 기본 batch 이하다.

### 4.3 청킹

- `minimum_tokens <= target_tokens <= max_tokens`
- `0 <= overlap_ratio <= 0.25`
- `max_heading_prefix_tokens < max_tokens`
- embedding max input tokens는 chunk max tokens 이상이어야 한다.

### 4.4 모델

- LLM revision과 embedding revision은 production에서 필수다.
- 로컬 LLM backend는 Apple Silicon에서 `mlx-lm`만 허용한다.
- `context_tokens`는 벤치마크가 승인한 값 집합에 포함돼야 한다.
- 모든 목적의 출력 상한과 reserved token을 합해 context를 넘지 않아야 한다.
- 임베딩 normalize는 FAISS inner product 사용 시 true여야 한다.

### 4.5 분류와 중복

- 세 가중치 합은 1.0이다.
- 임계값을 설정하면 `non_technical_threshold < technical_threshold`다.
- dedup semantic review lower bound는 semantic threshold보다 작아야 한다.
- 라벨 데이터 버전이 `unconfigured`면 자동 technical/non-technical 판정을 production에서 금지한다.

### 4.6 웹

- `enabled=false`이면 provider는 `disabled`, network concurrency는 실제 스케줄러에서 0이다.
- `enabled=true`이면 provider, secret ref, allowed domains가 비어 있을 수 없다.
- `allow_private_content`는 모든 환경에서 false만 허용한다.
- allowed domains에 wildcard 최상위 도메인을 허용하지 않는다.
- URL scheme은 HTTPS만 허용한다.

### 4.7 게시

- `required_evidence_coverage`는 production에서 1.0만 허용한다.
- `require_citations`와 `require_approval`은 production에서 true만 허용한다.

## 5. 환경 변수 매핑

허용 환경 변수는 다음으로 제한한다.

| 환경 변수 | 설정 경로 | 용도 |
| --- | --- | --- |
| `RAG_ENVIRONMENT` | `environment` | 환경 파일 선택 |
| `RAG_VAR_ROOT` | `paths.var_root` | 실행 데이터 루트 |
| `RAG_LOG_LEVEL` | `logging.level` | 로그 레벨 |
| `RAG_WEB_ENABLED` | `web.enabled` | 승인된 운영 전환 |
| `RAG_CONFIG_FILE` | 환경 설정 파일 | 명시 설정 경로 |

before·after root, 모델 ID, 모델 revision, 허용 도메인, ACL, 품질 임계값은 환경 변수로 덮어쓰지 못한다.

## 6. CLI Override 허용 목록

| override | 허용 명령 | 범위 |
| --- | --- | --- |
| source scope | `rag ingest` | 실행 입력 |
| inventory page size | `rag ingest` | 1~500 |
| benchmark context | `rag benchmark` | 4096, 16384, 24576, 32768 |
| benchmark batch | `rag benchmark` | 1, 2, 4, 8, 16 |
| max documents | 개발·평가 명령 | 양수 |
| dry run | 유지보수 명령 | boolean |

production 실행에서 모델, 보안, 승인, 근거 커버리지 override는 금지한다.

## 7. Pipeline Fingerprint

fingerprint 입력은 정렬된 JSON으로 직렬화한다.

```json
{
  "schema_version": 1,
  "code_version": "git-commit-or-build-id",
  "parser_versions": {},
  "normalization_version": "1",
  "chunker_version": "1",
  "tokenizer": {
    "id": "Qwen/Qwen3.6-27B",
    "revision": "pinned-revision"
  },
  "embedding": {
    "id": "BAAI/bge-m3",
    "revision": "pinned-revision",
    "options_hash": "64-hex"
  },
  "classification_policy_version": "1",
  "deduplication_version": "1",
  "llm": {
    "id": "mlx-community/Qwen3.6-27B-4bit",
    "revision": "pinned-revision",
    "quantization": "4bit"
  },
  "prompt_versions": {},
  "taxonomy_version": "1",
  "document_workspace_policy_version": "1",
  "web_policy_version": "1",
  "citation_verifier_version": "1"
}
```

전체 정규 JSON의 SHA-256이 `PipelineFingerprint`다. 실행 효율을 위해 단계별 sub-fingerprint도 계산하고 [pipeline.md](pipeline.md)의 증분 무효화 매트릭스에 사용한다.

## 8. 설정 로드 실패 코드

| 코드 | 조건 |
| --- | --- |
| `CONFIG_FILE_MISSING` | 필수 설정 파일 없음 |
| `CONFIG_PARSE_ERROR` | YAML 파싱 실패 |
| `CONFIG_UNKNOWN_KEY` | 스키마 외 키 |
| `CONFIG_TYPE_ERROR` | 타입 불일치 |
| `CONFIG_RANGE_ERROR` | 범위·관계 위반 |
| `CONFIG_PATH_ESCAPE` | 승인 루트 탈출 |
| `CONFIG_SECRET_REF_MISSING` | 활성화된 외부 웹 검색의 Keychain 참조 없음 |
| `CONFIG_BEFORE_WRITABLE` | before root가 AI 실행 계정에 쓰기 가능 |
| `CONFIG_WORKSPACE_OVERLAP` | before, after, var root 중첩 |
| `CONFIG_MODEL_UNPINNED` | production 모델 revision 미고정 |
| `CONFIG_THRESHOLD_UNCALIBRATED` | production 자동 판정 임계값 미설정 |
| `CONFIG_WEB_POLICY_INCOMPLETE` | 웹 활성화 조건 미충족 |

설정 오류는 워커 시작과 DB 쓰기 전에 실패한다.

## 9. 설정 테스트

- 기준 YAML 스키마 통과
- 각 필드 최소·최대·관계 경계
- 알 수 없는 키 거부
- 환경 변수 허용 목록 외 무시가 아니라 거부
- production의 unpinned model 거부
- 웹 활성화 필수값 검사
- before read-only·after write·root 비중첩 검사
- Confluence URL·secret·provider 같은 금지 설정 키 거부
- run ID와 상대 경로 escape fixture 차단
- 경로 탈출과 symlink 검사
- 동일 설정의 정규 JSON과 fingerprint 결정성
- 설정 변경별 단계 sub-fingerprint 무효화 확인
