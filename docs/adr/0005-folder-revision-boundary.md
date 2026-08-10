<!-- docs/adr/0005-folder-revision-boundary.md -->
# ADR-0005: Confluence API 제거와 폴더 리비전 경계

- 상태: Accepted
- 기준일: 2026-08-10

## Context

사내 문서를 직접 수집하려고 AI 또는 모델 실행 경계에 Confluence API 키를 제공하면 자격정보 노출, 과도한 원본 접근, 의도하지 않은 write-back, 감사 범위 확대 위험이 생긴다. 원본 문서와 AI 수정본을 같은 경로에 두면 기준선 손실과 결정적 비교 실패도 발생한다.

## Decision

- RAG 런타임에서 Confluence 소스 어댑터, base URL, API 키, access token, cookie 설정을 제거한다.
- 원본 시스템 export는 데이터 관리자 또는 별도 승인 자동화의 외부 책임으로 둔다.
- 승인된 export는 `data/before`에 불변 스냅샷으로 배치한다.
- AI 작업은 신규 `data/after/runs/<run_id>`에만 결과를 쓴다.
- 준비 도구가 before를 복사하고 입력 SHA-256 매니페스트를 생성한다.
- 비교 도구가 상대 경로별 added, modified, removed, unchanged와 전후 해시·텍스트 diff를 생성한다.
- existing run과 finalized run은 덮어쓰지 않는다.
- Qwen 워커는 파일·네트워크·비밀 저장소에 직접 접근하지 않는다.
- 프로젝트 스킬 실행기는 before 읽기, current run 쓰기, 비교에만 제한한다.
- finalization과 사람 승인을 마친 산출물만 별도 게시·write-back 절차에 전달한다.

## Consequences

장점:

- AI에 원본 시스템 자격정보가 노출되지 않는다.
- 수정 전·후 데이터와 모든 실행 이력이 명확히 분리된다.
- 파일 해시와 diff로 재현 가능한 검토가 가능하다.
- 원본 시스템 종류와 무관한 동일 파이프라인을 사용한다.
- 로컬 테스트 fixture를 빠르게 만들 수 있다.

비용:

- export와 write-back을 별도 운영 절차로 관리해야 한다.
- 실시간 Confluence 변경 감지는 제공하지 않는다.
- 원본 ACL은 sidecar 또는 제한적 기본값으로 전달해야 한다.
- 스킬 지침 외에 OS 권한과 샌드박스 정책을 실제로 구성해야 한다.
- 데이터셋과 run 보존 용량이 증가한다.

## Rejected Alternatives

### Confluence API 키를 Keychain에 저장하고 Coordinator가 조회

모델에 직접 전달하지 않아도 런타임의 침해 범위와 원본 접근 권한이 커지며, 이번 요구의 자격정보 비제공 원칙을 만족하지 않는다.

### Before 파일을 제자리 수정하고 Git diff 사용

Git 미추적 문서, 대용량 binary, 부분 실패, 운영 권한에서 기준선 보존을 보장하지 못한다.

### 하나의 After 디렉터리를 매번 덮어쓰기

이전 실행과 승인 증거가 사라지고 중단 복구와 회귀 비교가 불가능해진다.

### 모델에 광범위한 프로젝트 쓰기 권한 제공

프롬프트 인젝션이나 경로 생성 오류가 문서 밖의 코드·설정·원본을 오염시킬 수 있어 거부한다.

## Compliance

- Confluence adapter와 secret 설정 0
- before 실행 전후 hash 변화 0
- current 신규 run 밖 쓰기 0
- existing·finalized run overwrite 0
- path escape와 link fixture 100% 차단
- finalized run 입력·비교 매니페스트 완전성 100%
- 사람 승인 없는 원본 시스템 write-back 0
