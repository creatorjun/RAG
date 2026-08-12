<!-- docs/adr/0001-clean-architecture.md -->
# ADR-0001: Clean Architecture와 Hexagonal 경계

- 상태: Accepted
- 기준일: 2026-08-10

## Context

파서, BGE, MLX, FAISS, SQLite, 외부 검색은 교체 가능성과 실패 특성이 다르다. 모델·저장소 라이브러리를 유스케이스에 직접 결합하면 테스트, 리소스 회수, 보안 정책 적용, 향후 Qdrant 전환이 어려워진다.

## Decision

`domain`, `application`, `infrastructure`, `presentation`, `bootstrap` 계층을 사용한다.

- domain은 순수 엔터티, 값 객체, 정책만 가진다.
- application은 유스케이스, DTO, 포트를 정의한다.
- infrastructure는 소스, 파서, 모델, DB, 벡터, 웹, secret 어댑터를 구현한다.
- presentation은 CLI/API 요청을 유스케이스에 전달한다.
- bootstrap만 구체 구현을 조립한다.
- 실행 컨테이너와 런타임 진단값은 application 계약이며 구체 설정·저장소 타입을 노출하지 않는다.
- bootstrap은 factory를 Presentation controller에 주입하고, Presentation은 bootstrap이나
  infrastructure를 import하지 않는다.
- 동적 Job stage도 bootstrap이 전달한 source·workspace·model·structured generator factory만
  사용한다.
- 의존성은 바깥에서 안쪽으로만 향한다.
- 아키텍처 규칙을 CI의 AST·import 검사로 강제한다.

## Consequences

장점:

- 모델·검색·저장소 교체가 포트 뒤에 격리된다.
- 유스케이스를 fake adapter로 빠르게 검증한다.
- 네트워크와 파일 I/O를 명시 경계에서 통제한다.
- 리소스 소유권과 종료 계약을 어댑터별로 검증한다.

비용:

- DTO·mapper·포트 코드가 증가한다.
- 라이브러리 고유 기능을 도메인까지 직접 노출할 수 없다.
- 작은 기능도 계층별 계약을 먼저 설계해야 한다.

## Rejected Alternatives

### LangChain 또는 LlamaIndex 중심 구조

빠른 프로토타입에는 유리하지만 도메인 규칙, ACL, 멱등성, 외부 반출, 리소스 소유권이 프레임워크 체인에 섞일 위험이 있어 코어 아키텍처로 사용하지 않는다. 필요한 로더가 있으면 parser adapter 내부에서 제한적으로 사용할 수 있다.

### 단일 service 모듈

초기 파일 수는 적지만 모델·DB·웹 테스트 격리와 장기 유지보수 비용이 커지므로 거부한다.

## Compliance

- domain 외부 프레임워크 import 0
- application의 infrastructure import 0
- presentation의 infrastructure·bootstrap import 0 (`__main__.py` composition shim 제외)
- import 시 I/O 0
- 모든 외부 기술에 application port 존재
- bootstrap 외 구체 어댑터 생성 0
