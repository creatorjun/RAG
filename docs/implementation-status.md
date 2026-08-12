<!-- docs/implementation-status.md -->
# 구현 상태와 검증 기준선

- 기준일: 2026-08-12
- 애플리케이션 버전: `0.1.0`
- 현재 범위: Milestone 1 기반, 폴더 리비전 최소 수직 슬라이스, ADR-0006 Phase 1

## 1. 완료된 산출물

### 1.1 프로젝트 기반

- `.gitignore`, `.env.example`, `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `requirements-mlx.txt`
- `config/default.yaml`, `config/development.yaml`, `config/production.yaml`
- Python 3.10 이상 `src` 레이아웃과 `rag` 콘솔 진입점
- Pydantic 기반 strict 설정 스키마, 환경별 YAML 병합, 허용 환경 변수 제한
- Ruff, mypy strict, pytest, branch coverage 85% gate

기본 런타임 직접 의존성은 Pydantic과 PyYAML을 고정했다. Apple Silicon의 통합 문서 생성용
`mlx-lm`은 `requirements-mlx.txt`와 `local-mlx` optional dependency에 분리해 고정했다.
BGE-M3, FAISS, 파서 의존성은 대상 Mac 실측과 라이선스 검토가 끝난 뒤 별도 그룹으로 잠근다.
검증 가능한 `uv` 실행 파일이 현재 환경에 없어 `uv.lock`은 아직 생성하지 않았다.

### 1.2 Clean Architecture 기반

| 계층 | 구현 내용 |
| --- | --- |
| Domain | 오류·값 객체, 리비전 상태, DocumentJob 상태 머신·진행 불변 조건 |
| Application | revision 유스케이스, 공통 Progress DTO·Reporter, Job·Event 포트 |
| Infrastructure | 설정 loader, MLX 어댑터, 청킹·계획, 경로 보안, 원자 쓰기, 폴더 workspace, tree comparator |
| Presentation | `rag doctor`, `rag revision prepare`, `compare`, `finalize`, `rag document integrate` |
| Composition | `bootstrap.py` 단일 조립 지점과 명시적 close 경계 |

AST 기반 아키텍처 테스트가 Domain에서 바깥 계층으로 향하는 import와 Application에서 Infrastructure·Presentation으로 향하는 import를 차단한다.

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
| M1-16 | 완료 | `DocumentJobState`, 전이·terminal·진행 불변 조건 | SQLite repository 연결 |
| M1-17 | 부분 완료 | `ProgressEventDto`, Reporter, publisher 포트와 CLI 연결 | 이벤트 영속화·GUI 구독 |
| M1-18 | 완료 | 파일 Job 저장소, 원자 초기화, write-once JSON, path/link guard | 없음 |
| M1-19 | 대기 | DDL과 포트 계약 완료 | SQLite migration·repository 구현 |
| M1-30B | 완료 | after workspace, path guard, overwrite 차단 | OS 배포 ACL runbook |
| M1-30C | 완료 | 네 상태, hash, text diff, 원자 report | 대용량 binary 성능 시험 |
| M1-40 | 부분 완료 | 설정·경로·web disabled doctor | 모델·DB·디스크·권한 진단 |
| M1-43 | 완료 | prepare·compare·finalize CLI와 인수 테스트 | 운영 승인 UI 연동 |

## 3. 검증 결과

| 검사 | 결과 |
| --- | --- |
| pytest | 53 passed, 10 subtests passed |
| branch coverage | 87.12%, 기준 85% 통과 |
| 프로젝트 스킬 unittest | 4 passed |
| Ruff | 통과 |
| mypy strict | 54 source files 통과 |
| 아키텍처 import 경계 | 위반 0건 |
| editable package 설치 | 성공, `rag` 콘솔 스크립트 생성 |
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

## 4. 다음 구현 순서

1. M1-19 SQLite DocumentJob·ProgressEvent migration과 CAS transition을 구현한다.
2. `IntegrateDocuments`를 원본 검사, 계획, 생성, 검증, 게시 use case로 분리한다.
3. Evidence DTO·저장소와 원본 구조 요소 100% 배정 검사를 구현한다.
4. Claim Ledger, 관계 판정, Coverage Matrix와 TaskPacket을 순서대로 구현한다.
5. 결정적 assembler와 quality gate 후 MLX worker·GUI를 연결한다.

Milestone 2의 BGE 분류와 중복 제거는 위 기반 작업과 대상 Mac 실측 gate를 통과하기 전 production 코드로 추가하지 않는다.
