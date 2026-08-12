<!-- docs/implementation-roadmap.md -->
# 구현 작업 분해와 마일스톤 로드맵

현재 코드 기준 완료·진행·대기 상태와 실제 검증 결과는 [implementation-status.md](implementation-status.md)에서 관리한다. 이 문서는 목표 작업과 종료 gate의 기준을 유지한다.

## 1. 실행 원칙

- 마일스톤은 순서대로 진행하고 종료 gate를 통과하기 전 다음 production 기능을 병합하지 않는다.
- 기반 불변 조건, 계보, ACL, 체크포인트를 모델 품질 기능보다 먼저 구현한다.
- 각 작업은 코드, 단위 테스트, 통합 테스트, 문서 변경을 하나의 완료 단위로 본다.
- 모델·파서·인덱스 결과는 결정적 fixture와 계약 테스트로 검증한다.
- 외부 웹 기능은 내부 전용 Track B가 완료된 후 별도 보안 승인으로 시작한다.
- 구현 중 발견한 결정 변경은 코드를 먼저 바꾸지 않고 ADR을 먼저 제안한다.

## 2. 공통 Definition of Done

모든 작업은 다음을 만족해야 완료다.

1. 타입 검사와 정적 분석 통과
2. 신규·변경 동작 단위 테스트
3. 포트 또는 어댑터 계약 테스트
4. 실패·취소·리소스 종료 경로 테스트
5. 로그에 원문·비밀값이 없음을 확인
6. 계층 의존성 검사 통과
7. 관련 설계 문서와 실제 공개 타입 일치
8. 재실행 멱등성 또는 비멱등 사유 명시
9. 운영 메트릭과 안전한 오류 코드 포함
10. 기존 기준 계획을 변경하지 않음

### 2.1 ADR-0006 구현 순서

다음 세로 슬라이스는 다른 품질 기능보다 먼저 순서대로 구현한다.

1. Job 상태 머신과 진행 이벤트 DTO·포트
2. 파일 기반 Job 아티팩트 저장소와 SQLite Job/Event repository
3. 현재 `IntegrateDocuments`의 단계별 use case 분리와 Job Coordinator 연결
4. Evidence DTO·저장소와 입력 구조 요소 100% 배정 검사
5. Claim Ledger와 중복·충돌 관계
6. Coverage Matrix, TaskPacket, 고정 Task DAG
7. Task 실행·검증·부분 재작성
8. 결정적 Markdown assembler와 최종 품질 게이트
9. MLX Worker 프로세스와 취소·재개
10. PySide6 GUI와 완료 알림

각 단계는 이전 단계의 공개 계약과 테스트가 완료된 뒤 시작한다. GUI는 Application 계층을
우회하지 않는다.

## 3. Milestone 0: 기술 스파이크와 기준선

### 3.1 목표

대상 Mac에서 모델 런타임, 컨텍스트, 배치, 메모리 안전값을 측정하고 구현 선택을 고정한다.

### 3.2 작업

| ID | 작업 | 의존성 | 산출물 |
| --- | --- | --- | --- |
| M0-01 | Python 3.12·uv 실험 환경 | 없음 | 재현 설치 명령, lock 후보 |
| M0-02 | Qwen 모델 revision·hash manifest | M0-01 | 모델 매니페스트 |
| M0-03 | BGE 모델 revision·hash manifest | M0-01 | 모델 매니페스트 |
| M0-04 | `mlx-vlm` 텍스트 생성 스파이크 | M0-02 | 구조 출력·스트리밍 결과 |
| M0-05 | `mlx-lm` 호환 경로 검증 | M0-02 | 사용 또는 제외 근거 |
| M0-06 | Qwen 4K·16K·24K·32K 벤치마크 | M0-04 | benchmark JSON·그래프 |
| M0-07 | BGE 길이·배치 벤치마크 | M0-03 | batch 권장값 |
| M0-08 | BGE 종료 후 Qwen 메모리 회수 | M0-06, M0-07 | 프로세스 분리 검증 |
| M0-09 | 파서 후보 골든 샘플 비교 | M0-01 | 포맷별 파서 결정 |
| M0-10 | FAISS FlatIP smoke와 지속성 | M0-03 | 검색 기준선 |

### 3.3 고정 결정

- 텍스트 Qwen adapter runtime
- immutable model revisions
- production 기본 16K context
- 조건부 허용 context 집합
- BGE 초기 batch
- parser adapter 라이브러리
- FAISS 초기 index type
- worker idle timeout 후보

### 3.4 종료 Gate

- 16K·2048 출력에서 OOM 0, 최소 가용 6GB, swap 지속 증가 0
- BGE batch 8 또는 측정 대체값의 3회 안정 실행
- BGE worker 종료 후 Qwen load 성공
- 구조 JSON schema 성공률 100% 또는 교정 1회 포함 100%
- 모델·의존성·라이선스 매니페스트 완료
- ADR-0002의 최종 runtime 항목 승인

## 4. Milestone 1: 기반 아키텍처와 인제스천

### 4.1 패키지 골격

| ID | 작업 | 의존성 | 검증 |
| --- | --- | --- | --- |
| M1-01 | `src/enterprise_rag` 계층 패키지 | M0 | import smoke |
| M1-02 | 공통 ID·시간·해시 값 객체 | M1-01 | 속성 테스트 |
| M1-03 | 오류 분류와 안전 메시지 | M1-01 | 민감정보 fixture |
| M1-04 | 설정 스키마와 loader | M1-01 | 전체 경계 테스트 |
| M1-05 | bootstrap과 close stack | M1-04 | 부분 실패 종료 테스트 |
| M1-06 | 아키텍처 import 규칙 | M1-01 | CI gate |
| M1-07 | 프로젝트 문서 리비전 스킬 패키지 | M1-04 | skill validator·forward test |

### 4.2 저장 기반

| ID | 작업 | 의존성 | 검증 |
| --- | --- | --- | --- |
| M1-10 | SQLite migration framework | M1-04 | checksum·rollback 복구 |
| M1-11 | 핵심 source·revision·ACL schema | M1-10 | FK·CHECK 테스트 |
| M1-12 | stage·job·audit schema | M1-10 | 상태 전이 테스트 |
| M1-13 | CAS writer·reader | M1-04 | atomic write·hash |
| M1-14 | metadata repository mapper | M1-11, M1-12 | 계약 테스트 |
| M1-15 | checkpoint manager | M1-14 | 중복 commit 방지 |
| M1-16 | DocumentJob 상태 머신 | M1-02, M1-03 | 허용·금지 전이 |
| M1-17 | 진행 이벤트 DTO·publisher 포트 | M1-16 | sequence·건수·단조 증가 |
| M1-18 | Job artifact repository | M1-13, M1-16 | 원자 쓰기·재개 |
| M1-19 | SQLite Job·Event repository | M1-10, M1-16 | 상태 CAS·이벤트 순서 |

### 4.3 Coordinator와 워커 기반

| ID | 작업 | 의존성 | 검증 |
| --- | --- | --- | --- |
| M1-20 | 워커 envelope와 schema version | M1-03 | 직렬화 계약 |
| M1-21 | worker process factory | M1-20 | 시작·종료·crash |
| M1-22 | heartbeat·lease 회수 | M1-21, M1-15 | 실패 주입 |
| M1-23 | resource scheduler | M1-22 | 상호 배타 속성 테스트 |
| M1-24 | pipeline orchestrator 골격 | M1-15, M1-23 | fake stage DAG |

### 4.4 소스와 파서

| ID | 작업 | 의존성 | 검증 |
| --- | --- | --- | --- |
| M1-30 | filesystem source | M1-13 | symlink·변경 중 파일 |
| M1-30A | before folder source와 sidecar reader | M1-30 | read-only·ACL fallback |
| M1-30B | after run workspace와 path guard | M1-13 | overlap·escape·overwrite 차단 |
| M1-30C | folder tree comparator | M1-30B | 네 상태·hash·text diff |
| M1-31 | inventory·snapshot use case | M1-24, M1-30 | 멱등성 |
| M1-32 | PDF parser | M0-09, M1-21 | PDF golden |
| M1-33 | DOCX parser | M0-09, M1-21 | DOCX golden |
| M1-34 | HTML·Markdown parser | M0-09, M1-21 | AST golden |
| M1-35 | page-selective OCR | M1-32 | scan golden |
| M1-36 | normalization pipeline | M1-32~35 | source span |
| M1-37 | structure-aware chunker | M1-36 | token·boundary |

### 4.5 CLI

| ID | 작업 | 의존성 | 검증 |
| --- | --- | --- | --- |
| M1-40 | `rag doctor` 기반 검사 | M1-05, M1-13 | read-only smoke |
| M1-41 | source add/list | M1-14 | config·DB |
| M1-42 | ingest·run status·cancel | M1-24, M1-31 | end-to-end |
| M1-43 | revision prepare·compare·finalize | M1-30B, M1-30C | before/after end-to-end |

### 4.6 종료 Gate

- 지원 포맷 골든 세트 파서 gate 통과
- source span 없는 청크 0
- 같은 입력의 두 실행에서 결정적 revision·chunk ID
- 변경 없는 재실행 parse 0회
- 손상 문서 격리 후 다른 문서 계속
- 워커 crash 후 job 회수와 중복 결과 0
- SQLite integrity·foreign key 통과
- before 실행 전후 hash 변화 0
- 기존·finalized run overwrite 0
- Confluence URL·secret 설정 키와 네트워크 호출 0

## 5. Milestone 2: Track A

### 5.1 임베딩과 분류

| ID | 작업 | 의존성 | 검증 |
| --- | --- | --- | --- |
| M2-01 | BGE worker adapter | M0-07, M1-23 | descriptor·batch |
| M2-02 | embedding record 저장 | M2-01, M1-14 | vector hash |
| M2-03 | 라벨 데이터 관리 도구 | M1-14 | group split |
| M2-04 | 중심점 builder | M2-01, M2-03 | manifest |
| M2-05 | metadata·rule scorer | M1-37 | feature fixture |
| M2-06 | classification policy | M2-04, M2-05 | threshold grid |
| M2-07 | uncertain review flow | M2-06 | append-only decision |

### 5.2 중복

| ID | 작업 | 의존성 | 검증 |
| --- | --- | --- | --- |
| M2-10 | exact chunk duplicate | M1-37 | lineage 보존 |
| M2-11 | MinHash candidate | M2-02 | near recall |
| M2-12 | semantic candidate | M2-02 | top-K 후보 |
| M2-13 | conflict guard | M2-11, M2-12 | version·polarity fixture |
| M2-14 | cluster builder | M2-13 | purity·direct canonical edge |
| M2-15 | canonical policy | M2-14 | 우선순위 결정성 |

### 5.3 FAISS

| ID | 작업 | 의존성 | 검증 |
| --- | --- | --- | --- |
| M2-20 | generation builder | M2-02 | file hash·count |
| M2-21 | ID map과 ACL filter | M2-20 | leakage 0 |
| M2-22 | verify·activate·rollback | M2-20 | 실패 원자성 |
| M2-23 | retrieval service | M2-21, M2-22 | Recall@10 |

### 5.4 종료 Gate

- technical recall 95%, precision 85%
- 중요 보안·운영 문서 recall 100%
- duplicate precision 98%, conflict 오병합 0
- Recall@10 90%, ACL leakage 0
- FAISS 활성화 실패 시 이전 세대 유지
- 4시간 Track A 안정 실행과 OOM 미복구 0

## 6. Milestone 3: Track B 내부 검증

### 6.1 Qwen 런타임

| ID | 작업 | 의존성 | 검증 |
| --- | --- | --- | --- |
| M3-01 | Track B worker | M0-04, M1-23 | exclusive lease |
| M3-02 | token budget calculator | M3-01 | overflow 거부 |
| M3-03 | structured generation adapter | M3-01 | schema·repair |
| M3-04 | prompt registry | M3-03 | version·hash |

### 6.2 주장과 내부 검증

| ID | 작업 | 의존성 | 검증 |
| --- | --- | --- | --- |
| M3-10 | validation priority | M2-23 | 결정성 |
| M3-11 | evidence bundle builder | M2-14 | ACL·token budget |
| M3-12 | claim extraction | M3-03, M3-11 | quote exact match |
| M3-13 | claim persistence | M3-12 | source FK |
| M3-14 | internal conflict detection | M3-13 | version·scope fixture |
| M3-15 | validation report skeleton | M3-14 | internal-only relation |

### 6.3 승인

| ID | 작업 | 의존성 | 검증 |
| --- | --- | --- | --- |
| M3-20 | approval repository | M1-14 | append-only chain |
| M3-21 | review list·detail CLI | M3-15 | ACL·redaction |
| M3-22 | review decide CLI | M3-20 | 사유 필수 |

### 6.4 종료 Gate

- claim precision 95%, recall 90%
- quote와 source span 정확도 100%
- unsupported claim 0
- 구조 출력 실패가 검토 큐로 안전하게 이동
- 웹 disabled 상태 DNS·HTTP 0
- BGE 종료·Qwen 적재 반복에서 메모리 지속 증가 없음

## 7. Milestone 4: 제한적 웹 검증

### 7.1 정책과 Gateway

| ID | 작업 | 의존성 | 검증 |
| --- | --- | --- | --- |
| M4-01 | public entity schema·사전 | M3-12 | 승인 workflow |
| M4-02 | query template builder | M4-01 | free text 미전송 |
| M4-03 | sensitive detector | M4-02 | 300 security fixture |
| M4-04 | egress policy | M4-03 | allow·block·review |
| M4-05 | DNS·URL·redirect validator | M4-04 | SSRF fixture |
| M4-06 | Tavily search adapter | M4-05 | rate·timeout |
| M4-07 | evidence fetch·CAS | M4-05 | size·content type |

### 7.2 검증

| ID | 작업 | 의존성 | 검증 |
| --- | --- | --- | --- |
| M4-10 | evidence trust tier | M4-07 | domain fixture |
| M4-11 | claim validation prompt | M3-03, M4-10 | relation F1 |
| M4-12 | deterministic validation guard | M4-11 | no evidence 확정 차단 |
| M4-13 | proposed revision | M4-12 | 세 상태 분리 |
| M4-14 | external review UI·CLI | M3-21, M4-13 | approval gate |

### 7.3 종료 Gate

- 민감 query 전송 0
- SSRF 우회 0
- 웹 prompt injection 도구 실행 0
- 관계 macro F1 90%
- insufficient를 confirmed·outdated로 확정 0
- 모든 egress 결정 audit event
- 보안팀 ADR-0004 승인

## 8. Milestone 5: 합성과 게시

### 8.1 합성

| ID | 작업 | 의존성 | 검증 |
| --- | --- | --- | --- |
| M5-01 | taxonomy registry | M2-23 | version·fallback |
| M5-02 | Evidence store와 card builder | M3-20, M4-13 | Evidence·Derived 분리 |
| M5-03 | Claim Ledger builder | M5-02 | 모든 Claim의 Evidence 연결 |
| M5-04 | Claim 관계 판정 | M5-03 | duplicate·repeat·conflict |
| M5-05 | Coverage Matrix·Task planner | M5-04 | 원본 요소·필수 Claim 100% |
| M5-06 | TaskPacket·TaskOutput schema | M5-05 | 직렬화·허용 Evidence |
| M5-07 | Task executor·validator | M3-03, M5-06 | 부분 재작성·완료 표식 |
| M5-08 | deterministic Markdown assembler | M5-07 | 동일 입력 동일 출력 |
| M5-09 | citation·coverage quality gate | M5-08 | quote·ACL·hash·완결성 |

### 8.2 게시

| ID | 작업 | 의존성 | 검증 |
| --- | --- | --- | --- |
| M5-10 | artifact CAS repository | M1-13 | atomic write |
| M5-11 | artifact generation builder | M5-09, M5-10 | manifest |
| M5-12 | publish approval | M3-20, M5-11 | 필수 승인 |
| M5-13 | activate·rollback | M5-12 | 이전 세대 유지 |
| M5-14 | topic index·full export | M5-13 | 생성 전용 파일 |
| M5-15 | before/after comparison report | M1-30C, M5-14 | 상태 합계·hash·diff |
| M5-16 | revision run finalization | M5-12, M5-15 | 이후 writer 거부 |

### 8.3 종료 Gate

- 근거 커버리지 100%
- citation accuracy 95% 이상
- unsupported·contradicted 문장 0
- 승인 없는 공개 변경 0
- conflict 누락 0
- ACL leakage 0
- 게시 실패 시 이전 artifact 세대 유지
- finalized run마다 입력·비교 매니페스트 존재
- before hash 불변과 current run 외 쓰기 0건

## 9. Milestone 6: 운영 준비

### 9.1 작업

| ID | 작업 | 의존성 | 검증 |
| --- | --- | --- | --- |
| M6-01 | JSONL 로그와 rotation | M1 | secret scan |
| M6-02 | metric collector | M2~M5 | 기준선 |
| M6-03 | health·read-only·recovery | M1-14 | 상태 전이 |
| M6-04 | backup command | M5-13 | manifest |
| M6-05 | restore command | M6-04 | empty host drill |
| M6-06 | CAS·generation cleanup dry-run | M6-04 | 참조 보존 |
| M6-07 | model upgrade shadow run | M3 | rollback |
| M6-08 | failure injection suite | 전체 | runbook 일치 |
| M6-09 | 4시간 mixed soak | 전체 | stability gate |
| M6-10 | 전체 코퍼스 dry run | 전체 | capacity report |
| M6-11 | folder permission·finalized run restore drill | M1-30B, M6-05 | 불변성·복구 |
| M6-20 | 기존 Presentation 통합 PySide6 application shell | M1-17, M1-24 | GUI import·종료·단일 instance |
| M6-21 | 실행/설정 탭, folder·model·prompt 설정 | M6-20, M1-30 | 설정 CAS·Job snapshot |
| M6-22 | 진행·체크포인트·event·LLM stream 상세 화면 | M6-21, M1-19 | Evidence별 Claim 재개·생성 문자열·건수·무결성 표시 |
| M6-23 | 결과·품질 보고서 화면 | M6-22, M5-16 | 상태별 동작 |
| M6-24 | 완료 알림 adapter | M6-23 | 게시 후 단일 알림 |

### 9.2 종료 Gate

- 빈 `var_root` 복구 성공
- 4시간 soak의 미복구 작업·고아 worker·OOM 0
- 모든 runbook 실제 명령 검증
- security·quality 전체 test 통과
- 운영 승인된 모델·설정·정책 fingerprint 고정
- rollback build, DB, vector, artifact 준비
- before snapshot과 finalized after run 복구·비교 성공

## 10. 병합 순서와 브랜치 게이트

의존성이 있는 작업은 다음 순서로 병합한다.

```text
domain types
-> application ports and DTOs
-> fake adapters and contract tests
-> persistence schema and repository
-> infrastructure adapters
-> use cases
-> orchestration
-> presentation
-> end-to-end tests
-> operational tooling
```

프로덕션 어댑터를 포트보다 먼저 병합하지 않는다. 유스케이스 테스트는 fake adapter로 먼저 완성한다.

## 11. 테스트 실행 계층

| 변경 유형 | 필수 테스트 |
| --- | --- |
| domain | unit, property, architecture |
| port·DTO | unit, schema, fake contract |
| parser | unit, parser golden, chunk integration |
| DB | migration, repository contract, backup fixture |
| BGE | adapter contract, classification, performance smoke |
| FAISS | generation, retrieval, ACL, rollback |
| Qwen | schema, claim, citation, target Mac smoke |
| web | security 전체, network contract |
| synthesis | claim grounding, citation, ACL |
| operations | failure injection, backup·restore |
| folder revision | path guard, before 불변, run overwrite, compare·finalize |
| Job·GUI | 상태 전이, 이벤트 순서, 재개, UI 무응답 방지, 알림 시점 |

## 12. 구현 중 금지되는 단축

- threshold를 평가 없이 임의 숫자로 production에 설정
- 원본 또는 기존 리비전 update·delete
- Qwen과 BGE를 Coordinator에 import하여 메모리 공유
- 모델 출력 JSON을 schema·quote 검사 없이 저장
- 검색 provider에 원 query 자유 텍스트 전달
- FAISS 파일을 active 위치에서 in-place 수정
- 승인 레코드 overwrite
- citation 실패 문장을 조용히 삭제해 게시
- 테스트를 위해 production 보안 검사 비활성
- 문서와 다른 상태값·필드명을 코드에 추가
- AI에 Confluence 자격정보 또는 원본 시스템 write-back 권한 제공
- `data/before` 수정이나 기존·finalized after run 덮어쓰기
- 대화 세션을 Job 상태나 재개 체크포인트로 사용
- Derived 산출물을 최종 사실의 Evidence로 인용
- 검증된 Task 섹션을 최종 모델 호출로 전체 재작성
- 품질 게이트 전에 `data/after` 게시 run 생성

## 13. 최종 인수 산출물

- 실행 가능한 Python 패키지와 lockfile
- 고정 모델·의존성·라이선스 매니페스트
- migration과 빈 DB 생성 절차
- 골든·보안·성능 평가 세트와 리포트
- 대상 Mac 벤치마크 기준선
- 운영 설정과 fingerprint
- backup·restore·rollback 증거
- 주제별 artifact 예시와 evidence manifest
- 검증된 `manage-document-revisions` 스킬과 권한 모델
- Oracle Linux 9.8 before 샘플과 before/after 비교 리포트 예시
- 현재 구현과 일치하는 `docs/` 전체
