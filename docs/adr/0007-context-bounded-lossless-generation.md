<!-- docs/adr/0007-context-bounded-lossless-generation.md -->
# ADR-0007: 컨텍스트 제한형 무손실 장문 처리

- 상태: Accepted
- 결정일: 2026-08-14

완료 표식·필수 섹션·coverage를 런타임 실패로 처리하는 부분은 2026-08-17의
[ADR-0008](0008-non-blocking-quality-observation.md)로 대체됐다. JSON을 읽을 수 없을 때의
bounded shard와 허용 참조 경계는 계속 유효하다.

## 1. 배경

모델이 선언한 context window 안에 요청이 들어간다는 사실만으로 긴 문서 품질이 보장되지는
않는다. 긴 입력의 중간에 있는 근거는 검색·추론 성능이 낮아질 수 있고, 입력 한도와 별개로 긴
출력은 학습된 생성 길이와 `max_output_tokens`에서 잘릴 수 있다. 이 프로젝트의 기존 경로에는
입력 token 초과만 batch 재시도로 전환하고 완료 표식 누락·불완전 JSON은 같은 크기로 반복하는
구간, 배치 경계 밖 Claim 관계를 비교하지 못하는 구간, 의미 동등 Claim을 관계로만 남겨 최종
문서에서 반복될 수 있는 구간이 있었다.

검토한 1차 자료:

- [Lost in the Middle](https://arxiv.org/abs/2307.03172): 긴 입력의 가운데 위치에서 관련 정보
  활용 성능이 낮아질 수 있음을 보인다.
- [Chain-of-Agents](https://arxiv.org/abs/2406.02818): 전체 입력을 짧은 구간으로 순차 처리하고
  외부 상태로 합성하는 long-context 분해 방식을 제안한다.
- [RAPTOR](https://arxiv.org/abs/2401.18059): 재귀 군집·요약과 여러 추상화 수준의 탐색을
  제안한다.
- [GraphRAG](https://arxiv.org/abs/2404.16130)와
  [공식 Global Search 설계](https://github.com/microsoft/graphrag/blob/main/docs/query/global_search.md):
  corpus 전역 질문을 bounded map/reduce로 처리한다.
- [LongRAG](https://arxiv.org/abs/2406.15319): 과도한 미세 청킹 대신 관련 문서를 더 큰 retrieval
  unit으로 묶어 문맥을 보존한다.
- [LongWriter](https://arxiv.org/abs/2408.07055): AgentWrite가 장문 생성을 작은 작성 과제로
  분해해 단일 응답 길이의 한계를 우회한다.

## 2. 결정

### 2.1 입력 처리

1. context window 확장은 최적화일 뿐 정확성 보장이 아니다. 지원되지 않는 RoPE scaling이나
   YaRN을 런타임에서 임의 활성화하지 않는다.
2. 모든 원본 Evidence를 Claim 추출 단계에서 각각 처리한다. top-k 밖 Evidence를 최종 처리
   대상에서 제거하지 않는다.
3. Evidence 본문은 최종 근거 경로에서 LLM 요약으로 압축하지 않는다. Claim은 원본 Evidence
   ID를 계속 소유하며 최종 검증에서 역참조한다.
4. MLX 호출 직전에 실제 tokenizer로 system+user prompt를 계수하고 출력·예약 token을 뺀
   입력 예산을 초과하면 `TOKEN_BUDGET_EXCEEDED`로 중단한다.
5. per-call 출력 상한은 사용자가 지정한 값과 context window 절반 중 작은 값이다. 장문 전체
   길이는 아래 shard 병합으로 확장하고, 한 호출이 입력 공간을 잠식하지 않게 한다.

### 2.2 출력 처리

1. 완료 표식 누락, JSON parse 실패, schema 불일치는 단순 재시도 대상이 아니라 출력 잘림
   가능성이 있는 `recoverable split signal`이다.
2. Claim 추출은 전체 종류 출력이 두 번 실패하면 Claim kind 집합을 재귀 분할한다.
3. 관계 판정과 Task 계획은 입력 초과뿐 아니라 불완전 구조 출력도 Claim 집합을 재귀 분할한다.
4. Task 작성은 owned Claim이 8개를 넘으면 선제 분할한다. 실패 시 Claim, required section,
   context Claim, Evidence 순으로 재귀 분할한다.
5. shard 결과는 LLM에 다시 요약시키지 않는다. 코드는 section 순서, Markdown, 사용 Claim,
   Evidence marker, conflict 목록을 합집합으로 결정론적으로 병합한다.
6. 모델 prompt와 출력에서는 64자리 내부 ID 대신 호출 범위의 `C000001`, `E000001`을 사용하고,
   parse 직후 허용 목록의 원래 ID로 복원한다. 알 수 없는 ref와 잘못된 marker는 거부한다.
7. 최종 문서는 검증된 Task section을 코드가 조립한다. 전체 문서를 마지막 LLM 호출로 다시
   쓰지 않는다.

### 2.3 중복과 관련 문맥

1. 관계 후보는 원본 경로, 전체 문장 순서, Claim kind뿐 아니라 token inverted block과
   character 3-gram MinHash view로 생성한다. 이 후보 생성은 삭제 결정이 아니다.
2. `EXACT_DUPLICATE`와 `SEMANTIC_EQUIVALENT` 중 kind, 전제조건, 명령, 경고가 모두 같고 숫자·
   부정·금지·필수 같은 보호 token도 일치하는 쌍만 하나의 Claim으로 접는다. 안전 메타데이터가
   비어 있으면 최소 문자 shingle 유사도도 요구한다. 모든 Evidence ID는 합집합으로 보존한다.
3. 안전 메타데이터가 다르거나 conflict인 Claim은 병합하지 않는다.
4. Task 계획 batch는 Claim relation 연결 요소를 먼저 묶고 한도 안에서 packing한다. 관련
   절차·충돌이 단순 파일/문자열 경계 때문에 다른 계획 호출로 갈라지는 빈도를 줄인다.

## 3. 적용하지 않은 대안

- 원문 prompt compression: query-aware compression은 질의응답 비용을 줄일 수 있지만 명령,
  숫자, 부정, 전제조건을 삭제할 수 있어 근거 보존형 문서 생성에는 사용하지 않는다.
- 무제한 context 확장: 메모리와 prefill 비용이 증가하고 가운데 정보 활용 저하를 해결하지
  못하므로 correctness 경계로 사용하지 않는다.
- 전체 GraphRAG 도입: 현재 Job은 질의응답이 아니라 전체 기술 Claim coverage가 목적이다.
  향후 대화형 corpus 검색에는 community summary와 DRIFT를 별도 read model로 평가하되, 최종
  게시 coverage 경로를 대체하지 않는다.
- 모델 생성물을 다시 Evidence로 사용: 요약 손실과 오류 증폭 때문에 금지한다.

## 4. 결과

장문 전체 길이는 단일 모델 응답 한도와 분리된다. 처리 호출 수와 시간이 늘어날 수 있지만 각
호출은 작아지고 실패 범위가 좁아지며, 이미 저장된 Evidence별 Claim과 Task attempt는 재개할 수
있다. shard가 더 이상 나뉠 수 없는 최소 단위에서도 예산 또는 구조 검증이 실패하면 품질을 낮춰
게시하지 않고 명시적으로 Job을 실패시킨다.
