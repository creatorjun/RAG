<!-- docs/desktop-gui.md -->
# 로컬 RAG 데스크톱 GUI 설계

## 1. 결정

GUI는 별도 V2 애플리케이션이나 별도 파이프라인을 만들지 않는다. 기존 Clean Architecture의
`presentation`에 PySide6 데스크톱 진입점을 추가하고, CLI와 동일한 Application 유스케이스와
Job·Event·Checkpoint 저장소를 사용한다.

메인 윈도우는 `실행`과 `설정` 두 탭을 기본 정보 구조로 사용한다. 실행 중 설정 변경은 현재
Job에 반영하지 않으며 Job 생성 시점의 설정 스냅샷과 fingerprint를 끝까지 사용한다.

## 2. 화면 구조

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Local Document RAG       활성 Job: job-…       상태: RUNNING_TASKS │
├──────────────────────────────┬──────────────────────────────────────┤
│ 실행                         │ 설정                                 │
├──────────────────────────────┴──────────────────────────────────────┤
│ 선택한 탭                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

GUI는 한 프로세스에서 여러 창을 열지 않는 단일 사용자 데스크톱 도구로 시작한다. 모델 Worker는
GUI와 별도 프로세스이며 GUI 종료가 Job 취소를 뜻하지 않는다.

## 3. 설정 탭

설정 탭은 다음 영역으로 분리한다.

### 3.1 작업 공간

- 원본 문서 폴더
- 최종 결과 폴더
- 내부 체크포인트 폴더 표시(고급, 기본 읽기 전용)
- 폴더 읽기 가능 여부, before/after/var 중첩, 링크, 지원 파일 수 사전 검사

원본 폴더는 사용자 선택값이지만 Job 시작 시 불변 입력 manifest를 만들고 이후 변경을 감지한다.
최종 결과는 품질 게이트 통과 전까지 만들지 않는다.

### 3.2 Hugging Face 로컬 모델

- 이미 로컬 캐시에 있는 모델
- Hugging Face에서 검색 가능한 MLX 호환 생성 모델
- 모델 ID, commit revision, 양자화, context 길이, 예상 다운로드 크기와 라이선스
- 다운로드·검증 진행률, 캐시 경로, 오프라인 모드
- 현재 장비 메모리 적합성 결과

`최신`은 화면에 표시하는 탐색 결과다. Job이 사용하는 값은 선택 시 해석한 정확한 commit
revision과 파일 hash다. 실행 중 자동 업데이트하지 않으며 새 revision은 별도 호환성 검사와
shadow run을 통과한 후 선택한다.

현재 구현은 `huggingface_hub` cache scan과 `mlx-community` 원격 카탈로그를 Application 포트로
제공한다. GUI는 ID, 정확한 40자리 commit, cache 여부·경로, snapshot/repository 크기, 양자화,
context, 라이선스, gated 여부, 수정 시각과 장비 적합성을 표로 표시한다. 적합성은 MLX 플랫폼,
모델 크기와 물리 메모리로 `SUPPORTED`, `TIGHT`, `TOO_LARGE`, `UNSUPPORTED`, `UNKNOWN`을
판정한다. 이는 load 전 보수적 사전 판정이며 실제 benchmark 승인을 대체하지 않는다.

오프라인 모드에서는 원격 검색 버튼을 비활성화하고 cache의 정확한 commit만 선택할 수 있다.
온라인 모드의 검색도 사용자의 버튼 동작으로만 수행하며 문서 내용은 요청에 포함하지 않는다.
Job 생성은 백그라운드에서 모델 선택을 다시 검증하고, cache miss나 비호환 모델이면 Job
아티팩트를 만들기 전에 거부한다.

원격 모델 다운로드는 `PREFLIGHT → DOWNLOADING → VERIFYING → COMPLETED` 상태를 사용한다.
사전 단계에서 exact commit의 dry-run 파일 목록으로 실제 전송 바이트를 계산하고, 그 용량에
5GiB 안전 여유를 더한 값보다 cache volume의 가용 공간이 작으면 시작하지 않는다. GUI는
전송 바이트, 전체 파일 완료 건수와 백분율을 표시한다. 다운로드는 GUI당 하나만 허용하며
사용자 취소와 GUI 종료 시 cancellation event를 전달한다. 불완전 임시 파일은 snapshot으로
간주하지 않는다.

완료 후 commit 이름의 snapshot 디렉터리, 유효한 `config.json`, 최소 하나의 MLX 가중치 파일
(`.safetensors` 또는 `.npz`)과 Hugging Face cache catalog의 동일 model ID·commit·경로를
다시 대조한다. 이 검증을 모두 통과한 뒤에만 카탈로그를 `cached=true`로 갱신하고 GUI를
오프라인 모드로 되돌린다. blob 전송 무결성과 incomplete snapshot 판정은 고정된
`huggingface_hub` content-addressed cache 계약을 사용한다.

### 3.3 프롬프트

프롬프트 계층은 다음 순서를 고정한다.

```text
고정 보안·비신뢰 입력 정책
→ 고정 Evidence·출처 정책
→ 사용자 추가 시스템 지침
→ Job 작업 지시
→ 불변 TaskPacket
```

사용자 추가 시스템 지침은 빈 값일 수 있고 최대 길이를 제한한다. 고정 정책을 편집·삭제하거나
도구 권한, 네트워크 권한, 허용 Evidence 범위를 넓힐 수 없다. 저장 전에 결합 순서와 fingerprint를
미리 보여주되 원문 Evidence는 설정 화면에 포함하지 않는다.

### 3.4 실행 정책

- Task 최대 시도 횟수(1~3)
- context·출력 토큰 상한
- 품질 실패 시 자동 부분 재작성 여부
- 게시 완료 알림 여부
- 오프라인 모드

보안·Coverage·출처 게이트는 사용자가 비활성화할 수 없다.

## 4. 실행 탭

실행 탭은 단순 progress bar가 아니라 재개 가능한 Job 운영 화면이다.

### 4.1 작업 제어와 요약

- 새 Job 생성, 시작, 안전 취소, 재개
- Job ID, 입력 폴더, 결과명, 모델 ID·revision, 설정 fingerprint
- 현재 상태, 전체 진행률, 시작·갱신 시각, 경과 시간
- 문서·Evidence·Claim·Task·검증 완료/전체 건수

### 4.2 체크포인트 패널

| 체크포인트 | 저장 상태 | 건수 | 재개 가능 | 상세 |
| --- | --- | ---: | --- | --- |
| Job 정의 | 저장됨/없음 | 1 | 예 | 설정 fingerprint |
| 원본 manifest | 저장됨/없음 | 문서 수 | 예 | 입력 hash |
| Evidence | 저장됨/없음 | Evidence 수 | 예 | coverage |
| Claim Ledger | 저장됨/없음 | Claim 수 | 예 | 관계·충돌 수 |
| Task plan | 저장됨/없음 | Task 수 | 예 | DAG·coverage |
| Task attempts | 진행/완료 | 검증 수/전체 | 부분 | 실패 코드 |
| 조립 초안 | 저장됨/없음 | 1 | 예 | 문서 SHA-256 |
| 최종 게이트 | 통과/실패/대기 | 검사 수 | 조건부 | 품질 오류 코드 |
| 게시 run | 게시됨/없음 | 파일 수 | 아니요 | 비교 보고서 |

파일 존재만으로 저장 완료를 판정하지 않는다. JSON schema, Job ID, 입력 hash와 문서 digest를
검증한 경우만 `저장됨`으로 표시한다. 부분 파일과 알 수 없는 파일은 `손상/검토 필요`다.

### 4.3 이벤트와 품질 상세

- sequence 순서의 단계 이벤트 타임라인
- 현재 태스크와 attempt, 재작성 이유
- 마지막 정상 체크포인트와 재개 가능 단계
- Claim/Evidence/source coverage, 충돌 노출, 실패한 품질 항목
- 최종 문서·품질 보고서·before/after 비교 보고서 열기

이벤트 화면에는 원문, 전체 모델 응답과 비밀값을 표시하지 않는다.

## 5. Presentation 경계

`presentation/gui`는 Widget과 ViewModel만 소유한다. 다음 작업을 직접 수행하지 않는다.

- SQLite SQL 실행
- Job artifact 디렉터리 탐색
- Hugging Face HTTP 호출과 모델 다운로드
- MLX import·모델 적재
- `data/after` 파일 쓰기

ViewModel은 Application 유스케이스를 호출하고 immutable 화면 상태를 반환한다. 장시간 호출은
GUI event loop 밖에서 실행하며 화면 변경은 Qt signal로 main thread에 전달한다.

## 6. 설정과 Job 스냅샷

GUI 편집 설정은 `var/config/desktop-settings.json`에 원자적으로 저장한다. 이 값은 사용자의 다음
Job 기본값이며 배포·보안 설정 YAML을 대체하지 않는다. Job 생성 시 다음 값을
`var/jobs/<job_id>/definition.json`에 복사한다.

- source/output root
- 모델 ID, commit revision, context·output 한도
- 사용자 추가 시스템 지침과 결합 prompt fingerprint
- Task 시도 정책과 완료 알림 정책
- 전체 pipeline fingerprint

설정 저장은 revision compare-and-set으로 동시 창의 손실 업데이트를 거부한다.

## 7. 완료 알림

완료 알림은 `COMPLETED` 상태만 대상으로 하며 최종 파일, 품질 보고서, run manifest와 비교
보고서 커밋 뒤 정확히 한 번 발생한다. `NEEDS_ATTENTION`, `FAILED`, `CANCELLED`는 서로 다른
알림 유형을 사용하고 성공으로 표시하지 않는다.

## 8. 구현 순서

1. DesktopSettings DTO·저장소·Application 유스케이스
2. JobDashboard DTO와 체크포인트 검사 유스케이스
3. PySide6 application shell과 실행/설정 탭
4. 설정 탭 저장·검증과 Job 설정 스냅샷
5. 실행 탭 이벤트 polling·체크포인트·품질 상세
6. Coordinator 실제 단계와 별도 MLX Worker 연결
7. 완료 알림과 macOS application packaging

## 9. 현재 구현 경계

현재는 1~6의 실행 수직 경로를 기존 코드에 통합했다. `새 작업 생성` 후
`파이프라인 시작/재개`를 누르면 Job별 로컬 프로세스가 manifest, Evidence, Claim,
Task attempt, 최종 품질 게이트와 게시 run을 체크포인트하며 수행한다. 단계 완료
event와 attempt를 사용해 중단 지점에서 멱등 재개한다.

Worker 생존 상태는 Job별 runner token·PID·launch sequence와 5초 heartbeat로 저장한다.
실행 탭은 `STARTING`, `HEALTHY`, `STALE`, `EXITED`, `FAILED`, 마지막 heartbeat 경과 시간과
안전한 오류 코드를 표시한다. OS 파일 lock이 실제 중복 실행 권한의 기준이고,
`runner-state.json`은 GUI 관측과 감사 전용이다.

남은 범위는 생성 호출 중 즉시 취소,
결과·품질·비교 보고서 열기, exactly-once 완료 알림과 macOS packaging이다.
