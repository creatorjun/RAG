<!-- docs/README.md -->
# RAG 시스템 상세 설계 문서 인덱스

## 1. 문서 목적

이 디렉터리는 루트의 [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md)를 구현 가능한 설계 계약으로 구체화한다. 기준 계획의 목표, 모델 선택, 품질 게이트, 보안 원칙은 변경하지 않는다. 문서 간 충돌이 발생하면 다음 우선순위를 적용한다.

1. `IMPLEMENTATION_PLAN.md`
2. 승인된 ADR
3. 아키텍처와 데이터 계약 문서
4. 운영·평가·로드맵 문서

구현 중 기준 계획을 변경해야 하는 경우 먼저 새 ADR을 작성하고, 승인 후 관련 문서를 같은 변경 집합에서 동기화한다.

## 2. 문서 목록

| 문서 | 독자 | 구현 시점 | 책임 범위 |
| --- | --- | --- | --- |
| [architecture.md](architecture.md) | 아키텍트, 전체 개발자 | 최초 | 시스템 경계, 프로세스 구조, 의존성, 동시성, 리소스 소유권 |
| [module-design.md](module-design.md) | Python 개발자 | 최초 | 계층별 모듈 책임, 엔터티, 유스케이스, 어댑터 매핑 |
| [contracts.md](contracts.md) | 코어·인프라 개발자 | 최초 | 포트, DTO, 워커 메시지, 예외, 취소 계약 |
| [data-model.md](data-model.md) | 백엔드·데이터 개발자 | Milestone 1 | SQLite 스키마, ID, 파일 저장, FAISS 세대, 마이그레이션 |
| [pipeline.md](pipeline.md) | 파이프라인 개발자 | Milestone 1~5 | 단계 상태, 멱등성, 재시도, 분류, 중복, 검증, 합성 알고리즘 |
| [configuration.md](configuration.md) | 전체 개발자, 운영자 | 최초 | 설정 스키마, 우선순위, 유효성 검증, 파이프라인 지문 |
| [security.md](security.md) | 보안 담당자, 개발자 | 전체 | 신뢰 경계, ACL, 외부 반출, SSRF, 인젝션, 비밀정보, 감사 |
| [operations.md](operations.md) | 운영자, SRE | Milestone 0, 6 | 설치, 벤치마크, 실행, 백업, 복구, 장애 대응, 업그레이드 |
| [evaluation.md](evaluation.md) | QA, 도메인 전문가 | Milestone 0~6 | 골든 세트, 지표, 합격 기준, 성능·보안·회귀 평가 |
| [implementation-roadmap.md](implementation-roadmap.md) | 기술 리드, 구현자 | 전체 | 작업 순서, 산출물, 의존성, 완료 조건, 병합 게이트 |
| [ADR-0001](adr/0001-clean-architecture.md) | 전체 개발자 | 최초 | Clean/Hexagonal 의존성 규칙 |
| [ADR-0002](adr/0002-local-model-runtime.md) | 모델·플랫폼 개발자 | Milestone 0 | Qwen MLX와 분리 워커 런타임 |
| [ADR-0003](adr/0003-vector-store.md) | 검색 개발자 | Milestone 2 | SQLite·FAISS 저장 전략과 Qdrant 전환 기준 |
| [ADR-0004](adr/0004-web-egress-policy.md) | 보안·검색 개발자 | Milestone 4 | 기본 차단 외부 검색과 비식별화 게이트 |

## 3. 계획 추적성

| 기준 계획 항목 | 상세 설계 문서 | 검증 문서 |
| --- | --- | --- |
| 목표 구조, Clean Architecture | `architecture.md`, `module-design.md`, ADR-0001 | `evaluation.md` 아키텍처 검사 |
| Two-Track 흐름 | `architecture.md`, `pipeline.md` | `evaluation.md` 단계·자원 시험 |
| 인제스천과 청킹 | `pipeline.md`, `contracts.md` | `evaluation.md` 파서·청킹 골든 세트 |
| BGE-M3 분류와 중복 제거 | `pipeline.md`, `module-design.md` | `evaluation.md` 분류·중복 지표 |
| SQLite·FAISS | `data-model.md`, ADR-0003 | `evaluation.md` 일관성·복구 시험 |
| Qwen 주장 추출과 합성 | `pipeline.md`, `contracts.md`, ADR-0002 | `evaluation.md` 근거·인용 평가 |
| 웹 검증 | `security.md`, `pipeline.md`, ADR-0004 | `evaluation.md` egress·인젝션 회귀 |
| 사람 승인과 게시 | `data-model.md`, `pipeline.md` | `evaluation.md` 승인·출처 완전성 |
| 36GB 메모리 운영 | `architecture.md`, `operations.md`, ADR-0002 | `evaluation.md` 성능·장시간 시험 |
| 설정 기준 | `configuration.md` | `evaluation.md` 설정 유효성 시험 |
| 마일스톤 | `implementation-roadmap.md` | 각 마일스톤 종료 게이트 |

## 4. 공통 용어

| 용어 | 정의 |
| --- | --- |
| 원본 | 사내 저장소에서 읽은 변경하지 않는 바이트 스트림 |
| 문서 | 소스 시스템에서 지속적으로 식별되는 논리 개체 |
| 리비전 | 특정 시점의 문서 내용, 메타데이터, ACL 스냅샷 |
| 정규화 문서 | 구조 요소와 출처 좌표를 보존한 파서 출력 |
| 청크 | 임베딩과 검색을 위한 제한된 토큰 범위의 파생 단위 |
| 정규본 | 중복 군집에서 우선 사용되는 멤버이며 다른 멤버를 삭제하지 않음 |
| 주장 | 하나 이상의 출처 범위가 지지하는 원자적 사실 후보 |
| 외부 근거 | 허용된 공개 URL에서 수집한 변경 불가 스냅샷 |
| 검증 보고서 | 내부 상태와 외부 상태의 관계와 신뢰도를 기록한 결과 |
| 변경 제안 | 원본을 수정하지 않고 별도 승인 대상으로 만든 수정 후보 |
| 근거 카드 | 합성 입력으로 사용하는 승인된 주장과 인용 묶음 |
| 산출물 | 주제별 Markdown, 인덱스, 충돌 목록, 근거 매니페스트 |
| 파이프라인 지문 | 코드, 설정, 모델, 프롬프트, 파서 버전을 해시한 재현성 식별자 |
| 인덱스 세대 | 원자적으로 활성화·롤백할 수 있는 FAISS 인덱스 버전 |

## 5. 전역 불변 조건

1. 원본 바이트와 기존 리비전은 수정하거나 삭제하지 않는다.
2. 모든 청크는 정확히 하나의 문서 리비전과 하나 이상의 `SourceSpan`을 가진다.
3. 모든 임베딩은 청크 콘텐츠 해시, 모델 리비전, 임베딩 설정에 연결된다.
4. 모든 게시 사실 문장은 내부 또는 외부 근거에 연결된다.
5. 승인되지 않은 변경 제안은 확정 사실로 게시되지 않는다.
6. 산출물의 유효 독자 집합은 모든 사용 근거 ACL의 교집합이다.
7. 원문과 사내 식별자는 외부 검색 요청에 포함되지 않는다.
8. Qwen 워커와 BGE 워커는 대상 36GB 환경에서 동시에 가속기 리스를 소유하지 않는다.
9. 완료된 단계는 같은 멱등성 키로 중복 커밋되지 않는다.
10. 모든 배포 가능 산출물은 실행 ID, 파이프라인 지문, 근거 매니페스트를 가진다.

## 6. 문서 유지 규칙

- 각 Markdown 파일 첫 줄에는 해당 경로만 HTML 주석으로 기록한다.
- 설명용 HTML 주석은 추가하지 않는다.
- 구현에서 공개 타입, 포트, 테이블, 상태 값이 바뀌면 같은 변경에서 문서를 갱신한다.
- ADR 상태는 `Proposed`, `Accepted`, `Superseded`, `Rejected` 중 하나만 사용한다.
- 예제 설정과 JSON은 실제 스키마 검증 테스트의 fixture로 재사용한다.
- 문서의 상대 링크와 Mermaid 구문은 CI에서 검사한다.
- 문서 기준 시각과 모델 리비전은 운영 릴리스마다 재검증한다.
