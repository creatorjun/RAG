<!-- docs/implementation-status.md -->
# 구현 상태와 검증 기준선

- 기준일: 2026-08-14
- 애플리케이션 버전: `0.1.0`
- 현재 범위: Milestone 1 Job 기반, ADR-0006 Phase 2, ADR-0007 무손실 장문 shard, 기존 Presentation 통합 GUI 기반

## 1. 완료된 산출물

### 1.1 프로젝트 기반

- `.gitignore`, `.env.example`, `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `requirements-mlx.txt`
- `config/default.yaml`, `config/development.yaml`, `config/production.yaml`
- Python 3.10 이상 `src` 레이아웃과 `rag` 콘솔 진입점
- Pydantic 기반 strict 설정 스키마, 환경별 YAML 병합, 허용 환경 변수 제한
- Ruff, mypy strict, pytest, branch coverage 85% gate

기본 런타임 직접 의존성은 Pydantic과 PyYAML을 고정했다. Apple Silicon의 통합 문서 생성용
`mlx-lm`과 모델 카탈로그용 `huggingface-hub`는 GUI/MLX optional dependency에 분리해 고정했다.
BGE-M3, FAISS, 파서 의존성은 대상 Mac 실측과 라이선스 검토가 끝난 뒤 별도 그룹으로 잠근다.
검증 가능한 `uv` 실행 파일이 현재 환경에 없어 `uv.lock`은 아직 생성하지 않았다.

### 1.2 Clean Architecture 기반

| 계층 | 구현 내용 |
| --- | --- |
| Domain | 오류·값 객체, 리비전 상태, DocumentJob 상태 머신·진행 불변 조건 |
| Application | revision·Job·모델 카탈로그 관리, Evidence·Claim·Task 계획/실행/검증, 결정적 조립과 최종 품질 게이트, 실행 계약·공통 취소/알림 정책 |
| Infrastructure | 설정 loader, Hugging Face 카탈로그, MLX·구조화 생성·stream 관측 어댑터, SQLite Job/Event, write-once Job·Claim draft·Task·최종 게이트 저장소, mutable runner lease, 폴더 workspace |
| Presentation | Application 실행 계약만 받는 `rag` controller, Job Worker controller, `rag-gui` View/ViewModel |
| Composition | `bootstrap.py` 단일 구체 조립 지점, Presentation factory 주입과 명시적 close 경계 |

AST 기반 아키텍처 테스트가 네 계층 전체의 허용 import를 검사한다. Domain→외부,
Application→Infrastructure/Presentation, Presentation→Bootstrap/Infrastructure를 차단하고,
동적 Job stage가 구체 Infrastructure 어댑터를 import하지 못하게 별도 검사한다.

### 1.3 폴더 리비전 경계

- `data/before`를 인벤토리하고 파일별 SHA-256과 byte count를 입력 매니페스트에 고정
- 링크·junction·reparse point·특수 파일·경로 중첩·경로 탈출 차단
- `data/after/runs/<run_id>` 신규 생성만 허용하고 기존 run 충돌 차단
- 준비 중 임시 디렉터리와 원자 rename을 사용해 부분 run 노출 방지
- 복사 직후 해시와 준비·비교 전후 before tree 해시 재검증
- added·modified·removed·unchanged 결정과 UTF-8 unified diff 생성
- JSON·Markdown 비교 보고서와 비교 보고서 해시 생성
- finalize 후 애플리케이션의 비교·finalize 경로 차단
- Confluence URL, API 키, 토큰, provider 설정과 네트워크 호출 없음

프로젝트 스킬의 `prepare_run.py`와 `compare_run.py`는 독립 복제 로직을 제거하고 같은 애플리케이션 유스케이스와 인프라 어댑터를 호출한다.

## 2. 구현 추적

| 로드맵 ID | 상태 | 현재 증거 | 남은 범위 |
| --- | --- | --- | --- |
| M1-01 | 완료 | `src/enterprise_rag` 계층과 import smoke | 없음 |
| M1-02 | 부분 완료 | run ID, SHA-256, clock·ID 포트 | 전체 문서·리비전 결정 ID |
| M1-03 | 완료 | `ApplicationError`, 고정 리비전 오류 코드, CLI 안전 출력 | 전체 파이프라인 오류 매핑 |
| M1-04 | 부분 완료 | 실행 가능한 초기 strict 설정과 경로 관계 검사 | 모델·청킹·분류·백업 전체 스키마 |
| M1-05 | 부분 완료 | 단일 bootstrap과 close 경계 | DB·워커가 추가될 때 `ExitStack` 적용 |
| M1-06 | 완료 | AST import 경계 테스트 | CI 실행 환경 연결 |
| M1-07 | 완료 | 프로젝트 리비전 스킬이 애플리케이션 코드 호출 | 공식 validator 재실행 |
| M1-16 | 완료 | `DocumentJobState`, 허용 전이·terminal·단조 진행 불변 조건 | 없음 |
| M1-17 | 부분 완료 | `ProgressEventDto`, SQLite 원자 이벤트·counter, Job별 모델 stream journal, GUI 2초 polling | 백그라운 구독·대규모 event paging |
| M1-18 | 완료 | 파일 Job 저장소, 원자 초기화, write-once JSON, path/link guard | 없음 |
| M1-19 | 완료 | checksum migration, Job CAS, Event·counter 원자 commit, 재개 조회 | 없음 |
| M1-22 | 완료 | 파일 lock+runner token 소유권, PID claim, 5초 heartbeat, 3회 누락 stale 판정, launch sequence 회수, 자식 process reaper | 없음 |
| M1-24 | 완료 | 고정 10단계 실제 어댑터, Job별 subprocess, event 기반 멱등 재개, SIGTERM·토큰 경계 즉시 취소·15초 watchdog 강제 종료 | 없음 |
| M5-02 | 부분 완료 | text chunk Evidence DTO, 결정 ID, 100% 배정 검사, 전용 파일 저장소 | parser 구조 요소·ACL Evidence |
| M5-03 | 완료 | Evidence 제한 Claim 추출, 출력 잘림 시 Claim kind 재귀 분할, Evidence별 write-once 재개, exact·안전한 semantic equivalent의 다중 Evidence 병합 | 없음 |
| M5-04 | 부분 완료 | 구조화 관계 판정, compact Claim ref, 입력 초과·불완전 출력 시 재귀 분할, 원본·문장·종류·token·3-gram MinHash 후보 view, known-pair·상충 검증 | 실제 대규모 평가 기반 후보 recall 보정 |
| M5-05 | 완료 | Claim 단일 소유, Evidence 100% Coverage, 순환 없는 고정 Task DAG | 없음 |
| M5-06 | 완료 | TaskPacket·TaskOutput strict 계약과 write-once attempt 저장 | 없음 |
| M5-07 | 부분 완료 | JSON 전용 MLX stream, 실제 tokenizer 예산, per-call context 절반 출력 cap, 8 owned Claim 선제 shard, Claim·section·context·Evidence 재귀 분할과 compact ref 무손실 병합, 실패 Task 최대 3회 | Metal 압력 감시·실모델 장문 benchmark |
| M5-08 | 완료 | 계획 순서 기반 Markdown 조립, Evidence→source 변환, 전체 모델 재작성 없음 | 없음 |
| M5-09 | 부분 완료 | Claim/Evidence/source 100% 게이트 통과 후만 revision run·비교 보고서 게시 | 의미 정확도·인용 정확도 평가 세트 |
| M1-30B | 완료 | after workspace, path guard, overwrite 차단 | OS 배포 ACL runbook |
| M1-30C | 완료 | 네 상태, hash, text diff, 원자 report | 대용량 binary 성능 시험 |
| M1-40 | 부분 완료 | 설정·경로·web disabled doctor | 모델·DB·디스크·권한 진단 |
| M1-43 | 완료 | prepare·compare·finalize CLI와 인수 테스트 | 운영 승인 UI 연동 |
| M6-20 | 부분 완료 | 기존 `presentation` 내 PySide6 shell, 공통 시각 체계, macOS 독립 application palette, 스크롤 기반 실행·설정 화면, `rag-gui`, headless import·종료 smoke | 단일 instance·macOS packaging |
| M6-21 | 부분 완료 | 실행/설정 탭, 로컬/원격 HF 카탈로그, exact commit·cache·MLX/메모리 적합성, dry-run 디스크 검사, 다운로드 건수·바이트 진행/취소, snapshot 재검증, prompt 설정 CAS | 실측 benchmark 승인 |
| M6-22 | 부분 완료 | GUI 시작/재개, 10단계 event, Evidence별 Claim 건수·30~39% 진행률, 검증 전 LLM 실시간 stream, manifest~게시 run 무결성 체크포인트, PID·heartbeat 건강 상태 | 대규모 event paging |
| M6-23 | 완료 | 최종 문서·품질 JSON·비교 Markdown·합성 JSON 경로와 해시 재검증, coverage·비교 건수 GUI, 안전한 파일 열기 | 없음 |
| M6-24 | 완료 | Job snapshot 알림 정책, publication fingerprint 선점 영수증, Worker+GUI 중복 차단, macOS adapter, 전달 상태 GUI | 없음 |

## 3. 검증 결과

| 검사 | 결과 |
| --- | --- |
| pytest | 253 passed, 147 subtests passed |
| branch coverage | 85.36%, 기준 85% 통과 |
| 프로젝트 스킬 unittest | 4 passed |
| Ruff | 통과 |
| mypy strict | 155 source files 통과 |
| 아키텍처 import 경계 | Domain/Application/Infrastructure/Presentation 위반 0건, Job stage 구체 어댑터 import 0건 |
| editable package 설치 | 성공, `rag` 콘솔 스크립트 생성 |
| PySide6 GUI smoke | offscreen 2탭·macOS 고정 palette·오류 대비·중복 실행 차단·모델 카탈로그·다운로드 진행·Worker 취소·결과 품질·알림 상태 생성과 정상 종료, `rag-gui --help` 성공 |
| `rag doctor` | development 설정에서 성공, web disabled 확인 |
| Oracle Linux 9.8 CLI smoke | 입력 9개, added 1, modified 1, removed 1, unchanged 7, finalize 성공 |

현재 변경은 Apple Silicon Mac에서 검증했다. 고정된 Qwen 모델을 사용한 실제 9문서 실행에서
기존 3,072-token map 출력이 잘리는 사례를 재현했고, 완료 표식 검증이 불완전 출력을 차단함을
확인했다. 전체 처리량·메모리 회귀 기준선은 아직 별도 벤치마크가 필요하다.

### 3.1 전체 문서 통합 수직 슬라이스

- `rag document integrate` 단일 명령으로 새 revision run 준비, 전체 지원 텍스트 탐색, 구조 인식
  청킹, 계층형 map/reduce 통합, Markdown 결과 기록, 비교 보고서 생성을 연결했다.
- 기본 모델은 `mlx-community/Qwen3.6-27B-4bit`이며 설정에 Hugging Face 커밋 SHA를 고정했다.
- 모델은 첫 실행 시 MLX/Hugging Face 캐시에 다운로드되며 문서 본문은 로컬 추론 경계를
  벗어나지 않는다.
- 결과는 prepared 상태로 남겨 사람이 검토한 뒤 별도 `revision finalize` 명령으로 확정한다.
- 합성 매니페스트는 모델 ID·revision, 입력 파일 SHA-256, 청크·생성 횟수, 출력 SHA-256을
  기록한다.
- 완료 표식, 출처 정규화, 필수 구조 검증을 통과하기 전에는 after run을 만들지 않는다.
- 이 수직 슬라이스의 map/reduce는 호환 경로이며 ADR-0006 Task 파이프라인으로 단계적으로
  대체한다.
- 원본 탐색·읽기·청킹·source 배정은 `InspectIntegrationSources`로 분리했다. 모든 청크는
  정확히 하나의 원본 경로를 가지며 중복 청크 ID와 불완전 coverage를 거부한다.

### 3.2 ADR-0006 Evidence·Task 경로

- Evidence 하나씩 구조화 Claim을 추출하며 다른 Evidence ID 참조와 불완전 JSON을 거부한다.
- 유효한 Claim 배열은 빈 배열을 포함해 Evidence별 파일에 즉시 저장한다. 실패 복구는 저장되지 않은
  첫 Evidence부터 이어지며 체크포인트 건수를 GUI에 표시한다.
- 표현과 운영 세부가 동일한 Claim은 원본이 달라도 하나로 병합하고 모든 Evidence를 유지한다.
- 관계 판정기는 의미 있는 관계만 제안하고 코드는 알 수 없는 Claim, 중복 pair, `UNRELATED`
  출력을 거부한다.
- Claim 추출·관계·Task 계획은 최종 문서 출력 상한을 그대로 예약하지 않고 각각 2,048·2,048·
  4,096 토큰 상한을 사용한다. 관계·계획·Task 출력의 긴 ID는 요청 범위 compact ref로 치환한다.
- 전체 관계·계획 요청의 context 초과뿐 아니라 완료 표식 누락과 불완전 JSON도 최대 40개 Claim
  batch·재귀 분할로 전환한다. 관계 출력은 compact 3-tuple을 사용하고 실패 batch의 내부·교차
  pair 공간을 빠짐없이 분할한다. 관계 후보는 원본·문장·종류·token·MinHash view를 합치고 계획은
  relation component를 우선 packing한 뒤 namespace와 전체 Claim 단일 소유를 검증한다.
- Task 출력은 한 호출에 context의 절반보다 큰 출력을 예약하지 않는다. owned Claim 8개 초과는
  선제 shard하고, 실패 시 Claim·section·context Claim·Evidence 순으로 더 나눠 생성한 후 코드가
  Markdown과 사용 Claim·Evidence·conflict를 병합한다.
- Task planner의 제안 뒤 Claim 단일 소유, Evidence 100%, 의존성 존재와 DAG 무순환을 코드로
  다시 검증한다.
- 각 Task attempt는 구조화 JSON 원본과 검증 보고서를 별도 write-once 파일로 보존한다.
- 완료 표식, 허용 Claim/Evidence, 근거 marker, 코드 펜스, 명령·전제조건·경고, 충돌 노출을
  검사하고 실패한 Task만 최대 2회 재작성한다.
- Assembler는 계획된 Task·section 순서로만 조립하고 Evidence marker를 source 경로로 바꾼다.
- 최종 게이트는 Claim/Evidence/source coverage, 구조, marker, 해시를 확인하며 초안과 보고서는
  `derived/assembled-draft.md`, `control/final-validation.json`에 체크포인트한다.
- 고정 10단계 어댑터를 실제 파일·SQLite·revision workspace에 조립했다. 결정적
  구조화 생성기를 주입한 통합 시험에서 source manifest부터 `runs/<job_id>`의 생성 문서와
  비교 보고서까지 실제로 생성했다.
- GUI/CLI `start`는 파일 lock을 상속한 Job별 subprocess를 생성한다. 단계 event가 이미 commit됐으면
  다음 단계로, event 전이면 저장된 아티팩트를 재검증한 뒤 멱등 재개한다.
- launcher가 발급한 runner token을 자식 PID가 claim하고 5초마다 `runner-state.json`의
  heartbeat를 원자 갱신한다. GUI는 시작·정상·stale·종료·실패와 마지막 heartbeat 경과 시간을
  표시하며, 새 실행은 OS가 해제한 Job lock을 획득한 경우에만 launch sequence를 교체한다.
- 오프라인 Job은 pinned Hugging Face snapshot을 로컬 cache에서만 해석한다.
- 설정 탭은 로컬 Hugging Face cache와 사용자가 명시적으로 요청한 `mlx-community` 최신 검색을
  제공한다. exact commit, 크기, 양자화, context, 라이선스, gated 여부와 물리 메모리 적합성을
  표시하며 Job 생성 전에 동일 선택을 다시 검증한다.
- 현재 장비의 cache된 Qwen 27B snapshot은 16.08GB, 4-bit affine, 최대 context 262,144로
  인식됐고 보수적 예상 필요량 22.0GiB / 물리 메모리 36.0GiB로 `SUPPORTED` 판정을 받았다.
- 원격 모델 다운로드는 exact commit dry-run으로 실제 전송 대상 파일과 바이트를 고정하고
  5GiB 디스크 안전 여유를 검사한다. GUI에 파일·바이트 진행률과 취소를 전달하며 완료 뒤
  commit 경로, config, 가중치와 cache catalog를 재검증한다. 실패·취소 snapshot은 Job에 쓰지 않는다.
- Job 취소는 SQLite `CANCELLING` 선행, runner lease·process group 검증, `SIGTERM`, MLX
  `stream_generate` token 경계 취소 순서로 처리한다. Worker가 15초 안에 정상 종료하지 않으면
  자기 process group만 `SIGKILL`한다. 미완성 구조 결과는 Task 결과나 게시 문서로 저장하지 않지만
  사용자가 요청한 진단용 생성 조각은 `runtime/model-stream.jsonl`에 검증 전 상태로 남을 수 있다.
- 게시 결과 reader는 최종 문서·비교 JSON·Markdown·합성 JSON과 품질 보고서의 경계, schema,
  건수와 SHA-256을 재검증한다. 실행 탭은 coverage와 비교 건수, 검증된 파일 열기를 제공한다.
- 완료 Worker와 GUI recovery는 같은 publication fingerprint receipt를 사용한다. 한 호출자만
  macOS 알림을 실행하고 `CLAIMED`, `DELIVERED`, `FAILED`를 영속화해 중복 알림을 차단한다.
- 새 경로의 실제 Qwen 27B 전체 품질·처리량·메모리 회귀 평가는 아직 필요하다.

## 4. 다음 구현 순서

1. 모델 실측 benchmark 승인과 Metal 메모리 압력 감시를 추가한다.
2. 대규모 Claim 관계 판정의 후보 축소와 batch 예산을 구현하고 실제 27B 평가를 수행한다.
3. GUI 단일 instance와 macOS application packaging을 구현한다.

Milestone 2의 BGE 분류와 중복 제거는 위 기반 작업과 대상 Mac 실측 gate를 통과하기 전 production 코드로 추가하지 않는다.
