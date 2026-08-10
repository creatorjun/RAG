<!-- docs/adr/0004-web-egress-policy.md -->
# ADR-0004: 기본 차단 외부 검색과 비식별화 게이트

- 상태: Accepted
- 기준일: 2026-08-10

## Context

공개 웹 검증은 기술 버전과 보안 정보를 최신화하는 데 유용하지만 사내 문서에서 생성한 질의가 내부 IP, 고객명, 코드명, 장애 내용, 저장소 정보를 외부 검색 공급자에게 노출할 수 있다. 웹 콘텐츠 자체도 프롬프트 인젝션과 SSRF 유도 입력이 될 수 있다.

## Decision

- 외부 검색은 기본 비활성이다.
- Track B 모델 worker에는 네트워크 권한을 주지 않는다.
- Qwen의 자유 텍스트 검색 질의를 직접 전송하지 않는다.
- Qwen은 공개 entity와 intent만 구조화해 반환한다.
- Coordinator가 허용된 템플릿으로 전송 질의를 재구성한다.
- 원 query와 재구성 query 양쪽에서 민감정보를 검사한다.
- `PUBLIC`과 정책이 허용한 `INTERNAL` claim만 자동 egress 후보가 된다.
- `RESTRICTED`는 항상 차단한다.
- HTTPS, 허용 도메인, public IP, redirect 재검사, 응답 크기·형식 제한을 적용한다.
- 웹 페이지는 비신뢰 데이터이며 어떤 지시도 실행하지 않는다.
- 모든 allow, block, review 결정을 감사한다.

## Consequences

장점:

- 사내 원문과 식별자 외부 전송을 구조적으로 차단한다.
- 검색 공급자와 웹 콘텐츠를 명시적 신뢰 경계 밖에 둔다.
- 외부 장애 시 내부 전용 파이프라인을 계속 운영한다.

비용:

- 자유 질의보다 검색 recall이 낮을 수 있다.
- 공개 entity 사전과 허용 도메인 유지보수가 필요하다.
- CONFIDENTIAL 문서 검증은 사람 검토가 증가한다.

## Rejected Alternatives

### 원 청크를 검색 API 또는 외부 LLM에 전송

민감정보 통제가 불가능해 거부한다.

### 정규식 마스킹 후 자유 질의 전송

미등록 고객명, 코드명, 문맥 기반 비밀을 놓칠 수 있어 단독 방어로 사용하지 않는다.

### DuckDuckGo 무제한 fallback

공급자 장애가 보안 정책 완화를 정당화하지 않으므로 자동 fallback을 제공하지 않는다. 다른 공급자는 동일 `WebSearchPort`와 보안 계약을 통과해야 한다.

## Activation Gate

- 보안팀의 정책 버전 승인
- allowed domain 목록 승인
- Keychain secret 등록
- egress·SSRF·prompt injection fixture 100% 통과
- transmitted query 감사 검증
- 운영 중 즉시 disable 절차 검증
