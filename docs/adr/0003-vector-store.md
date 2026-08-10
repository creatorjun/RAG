<!-- docs/adr/0003-vector-store.md -->
# ADR-0003: SQLite·FAISS 초기 저장과 Qdrant 전환 기준

- 상태: Accepted
- 기준일: 2026-08-10

## Context

v1은 단일 Mac, 단일 운영자, 로컬 배치가 중심이다. 메타데이터, ACL, 계보, 작업 상태에는 트랜잭션이 필요하고 dense 검색에는 로컬 벡터 인덱스가 필요하다. 초기부터 별도 서버를 운영하면 배포·백업·장애 경계가 늘어난다.

## Decision

- SQLite를 메타데이터와 작업 상태의 system of record로 사용한다.
- FAISS를 dense vector 검색에 사용한다.
- cosine 유사도는 L2 정규화 벡터와 inner product로 구현한다.
- 첫 인덱스는 `IndexFlatIP`다.
- 인덱스는 불변 세대로 빌드·검증·활성화한다.
- ID map과 ACL metadata는 세대 매니페스트에 포함한다.
- active index를 in-place 수정하지 않는다.
- 삭제와 변경은 tombstone 후 새 세대에 반영한다.

## Qdrant Transition Trigger

다음 중 하나가 충족되고 측정으로 병목이 확인되면 Qdrant adapter를 구현한다.

- 활성 벡터 1,000,000개 초과
- 다중 사용자 동시 검색 요구
- 복잡한 payload filter가 FAISS prefilter 비용을 지배
- 검색 p95 250ms gate 반복 실패
- 전체 세대 rebuild 시간이 운영 창을 초과
- 인덱스가 단일 호스트 메모리 계획을 초과

전환은 `VectorIndexPort` 뒤에서 수행하고 SQLite의 문서·계보 system of record는 유지한다.

## Consequences

장점:

- 서버 없는 단순 로컬 배포
- 완전한 인덱스 파일 백업과 롤백
- 정확한 FlatIP 기준선
- SQLite transaction과 분리된 실패 안전 활성화

비용:

- FAISS 자체 metadata filter가 제한적이다.
- 증분 삭제가 새 세대 rebuild를 요구한다.
- 다중 writer와 분산 검색에 적합하지 않다.

## Rejected Alternatives

### Chroma를 system of record로 사용

문서 계보, 승인, 작업 상태, 감사 트랜잭션을 명확히 통제하기 위해 거부한다.

### 초기부터 Qdrant 서버

v1 단일 호스트 요구에 비해 운영 복잡도가 크므로 전환 trigger 전에는 사용하지 않는다.

### 벡터와 메타데이터를 SQLite blob으로만 저장

대규모 nearest neighbor 검색 성능과 인덱스 관리가 불리하므로 거부한다.
