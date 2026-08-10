<!-- docs/implementation-status.md -->
# 구현 상태와 검증 기준선

- 기준일: 2026-08-10
- 애플리케이션 버전: `0.1.0`
- 현재 범위: Milestone 1 기반과 폴더 리비전 최소 수직 슬라이스

## 1. 완료된 산출물

### 1.1 프로젝트 기반

- `.gitignore`, `.env.example`, `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`
- `config/default.yaml`, `config/development.yaml`, `config/production.yaml`
- Python 3.10 이상 `src` 레이아웃과 `rag` 콘솔 진입점
- Pydantic 기반 strict 설정 스키마, 환경별 YAML 병합, 허용 환경 변수 제한
- Ruff, mypy strict, pytest, branch coverage 85% gate

런타임 직접 의존성은 현재 구현에 필요한 Pydantic과 PyYAML만 고정했다. MLX, BGE-M3, FAISS, 파서 의존성은 Milestone 0의 대상 Mac 실측과 라이선스 검토가 끝난 뒤 별도 그룹으로 잠근다. 검증 가능한 `uv` 실행 파일이 현재 환경에 없어 `uv.lock`은 아직 생성하지 않았다.

### 1.2 Clean Architecture 기반

| 계층 | 구현 내용 |
| --- | --- |
| Domain | 오류 범주·안전 메시지, run ID·SHA-256 값 객체, 리비전·파일 변경 상태 |
| Application | revision prepare·compare·finalize 포트, DTO, 유스케이스 |
| Infrastructure | 설정 loader, clock·ID 어댑터, 경로 보안, 원자 쓰기, 폴더 workspace, tree comparator |
| Presentation | `rag doctor`, `rag revision prepare`, `compare`, `finalize` |
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
| M1-30B | 완료 | after workspace, path guard, overwrite 차단 | OS 배포 ACL runbook |
| M1-30C | 완료 | 네 상태, hash, text diff, 원자 report | 대용량 binary 성능 시험 |
| M1-40 | 부분 완료 | 설정·경로·web disabled doctor | 모델·DB·디스크·권한 진단 |
| M1-43 | 완료 | prepare·compare·finalize CLI와 인수 테스트 | 운영 승인 UI 연동 |

## 3. 검증 결과

| 검사 | 결과 |
| --- | --- |
| pytest | 17 passed, 5 subtests passed |
| branch coverage | 87.03%, 기준 85% 통과 |
| 프로젝트 스킬 unittest | 4 passed |
| Ruff | 통과 |
| mypy strict | 29 source files 통과 |
| 아키텍처 import 경계 | 위반 0건 |
| editable package 설치 | 성공, `rag` 콘솔 스크립트 생성 |
| `rag doctor` | development 설정에서 성공, web disabled 확인 |
| Oracle Linux 9.8 CLI smoke | 입력 9개, added 1, modified 1, removed 1, unchanged 7, finalize 성공 |

검증은 Windows 개발 환경의 Python 3.12.13에서 수행했다. 대상 MacBook Pro M4 Max의 MLX 처리량·메모리와 Python 3.10 호환 실행은 아직 검증하지 않았다.

## 4. 다음 구현 순서

1. Milestone 0 대상 Mac에서 Qwen·BGE·파서·FAISS 스파이크와 dependency·model manifest를 고정한다.
2. 전체 설정 스키마와 production 전용 검증, `uv.lock`, 공급망 hash를 완성한다.
3. SQLite migration, 핵심 schema, CAS, metadata repository를 구현한다.
4. filesystem source와 sidecar ACL reader를 리비전 workspace에 연결한다.
5. parser worker, normalization, structure-aware chunker의 골든 테스트를 구현한다.
6. Coordinator, checkpoint, resource scheduler와 ingest CLI를 연결한다.

Milestone 2의 BGE 분류와 중복 제거는 위 기반 작업과 대상 Mac 실측 gate를 통과하기 전 production 코드로 추가하지 않는다.
