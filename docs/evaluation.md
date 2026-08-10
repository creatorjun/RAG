<!-- docs/evaluation.md -->
# 품질·성능·보안 평가 설계

## 1. 평가 원칙

- 자동 LLM judge만으로 출시 여부를 결정하지 않는다.
- 업무 도메인 전문가가 만든 골든 정답을 기준으로 한다.
- 평가 데이터와 운영 데이터의 중복을 검사한다.
- 모델, 프롬프트, 파서, 청킹, 인덱스, 정책 변경을 모두 회귀 대상으로 본다.
- 평균뿐 아니라 최악 사례와 보안 실패를 별도 gate로 사용한다.
- 품질, 근거성, 보안 gate 중 하나라도 실패하면 production 승격을 금지한다.

## 2. 평가 데이터셋

### 2.1 분할

| 분할 | 용도 | 비율 | 변경 정책 |
| --- | --- | ---: | --- |
| train/calibration | 중심점과 임계값 보정 | 50% | 버전별 동결 |
| validation | 설정 선택 | 25% | 선택 후 동결 |
| test | 최종 gate | 25% | 개발자 비공개 |

같은 문서의 리비전, 중복 문단, 파생 요약은 다른 분할에 놓지 않는다. `document family ID`로 그룹 분할한다.

### 2.2 최소 표본

| 데이터셋 | 최소 수 | 층화 기준 |
| --- | ---: | --- |
| 문서 분류 | 400문서 | 기술·비기술, 부서, 포맷, 언어 |
| 청크 분류 | 2000청크 | 경계·표·코드·혼합 문서 |
| 중복 쌍 | 1000쌍 | exact, near, semantic, conflict, negative |
| 검색 질문 | 200질문 | frontend, backend, infra, security, policy |
| 주장 추출 | 300청크 | 7 claim type, 무주장 포함 |
| 외부 검증 | 150주장 | 최신·구식·충돌·미확인·부적용 |
| 합성 | 50주제 | 단일·다중 문서, ACL, 충돌 |
| 보안 | 300케이스 | egress, SSRF, injection, secret, ACL |
| 성능 | 고정 코퍼스 3종 | small, medium, stress |

### 2.3 포맷 층화

- 텍스트 PDF
- 스캔 PDF
- 표 중심 PDF
- DOCX 제목·표·목록
- HTML과 외부 승인 export 스냅샷
- Markdown 코드 블록
- Oracle Linux 9.8 샘플의 표·명령·공식 URL·중복 운영 점검
- 한글 중심, 영어 중심, 한영 혼합
- 손상, 암호화, 초대형 문서

## 3. 라벨 지침

### 3.1 기술 문서

`technical`은 시스템 구조, 소프트웨어, 하드웨어, API, 코드, 운영 절차, 장애 분석, 보안, 배포, 설정처럼 기술 실행에 직접 필요한 내용을 포함한다.

`non_technical`은 인사, 복지, 행사, 일반 행정, 기술 실행과 무관한 경영 문서다.

`uncertain`은 두 영역이 혼합됐거나 짧은 문맥만으로 결정할 수 없는 경우다. 라벨러는 억지로 이진 판정하지 않는다.

두 명이 독립 라벨하고 불일치는 제3 검토자가 확정한다. Cohen's kappa 0.8 미만이면 지침을 보완하고 재라벨한다.

### 3.2 중복

| 라벨 | 기준 |
| --- | --- |
| `exact` | 정규화 후 의미와 문구 동일 |
| `near_text` | 서식·경미한 표현 차이만 있고 사실 동일 |
| `semantic` | 문구는 다르지만 같은 적용 범위와 사실 |
| `conflict` | 같은 주제지만 수치·버전·극성·적용 범위 충돌 |
| `negative` | 관련은 있으나 별도 사실 |

최신이라는 이유만으로 duplicate로 라벨하지 않는다.

### 3.3 주장

하나의 claim은 주어, 관계, 목적어가 독립 검증 가능한 원자 사실이어야 한다. 여러 버전, 조건, 날짜를 한 claim에 묶지 않는다. 정확 quote와 source span을 필수로 라벨한다.

### 3.4 검증 관계

- `confirmed`: 같은 적용 범위에서 공개 근거가 지지
- `outdated`: 내부 상태가 과거에는 맞았으나 현재 공개 상태와 다름
- `contradicted`: 같은 시점·범위의 권위 근거와 충돌
- `not_applicable`: 제품, edition, channel, version 범위가 다름
- `insufficient_evidence`: 확정할 근거 부족

## 4. 파서와 청킹 평가

### 4.1 파서 지표

| 지표 | 계산 | Gate |
| --- | --- | ---: |
| 텍스트 보존율 | 골든 문자 중 정규화 일치 문자 | 98% 이상 |
| 제목 계층 정확도 | 정확 부모 제목 요소 비율 | 95% 이상 |
| 표 셀 보존율 | 정확 셀 텍스트·좌표 비율 | 95% 이상 |
| 페이지 매핑 정확도 | 골든 문단의 올바른 페이지 비율 | 99% 이상 |
| 코드 보존율 | 코드 토큰 일치율 | 99% 이상 |
| 손상 격리율 | 손상 fixture가 전체 실패 없이 격리 | 100% |

OCR 페이지는 문자 오류율과 수동 판독 가능성을 함께 평가한다. OCR 결과가 낮은 경우 원문을 확정 사실로 사용하지 않고 품질 경고를 연결한다.

### 4.2 청킹 지표

- 최대 토큰 초과 0건
- source span 없는 청크 0건
- 제목 경로 오류 1% 미만
- 문장 중간 절단 2% 미만
- 표·코드 비의도 분할 0건
- 같은 입력·설정의 chunk ID 불일치 0건

600, 800, 1000, 1200 목표 후보는 Retrieval Recall@10, 인용 정확도, BGE 처리량을 함께 비교한다. 기준 계획 기본값 800/1200/0.12를 변경하려면 ADR과 전체 회귀가 필요하다.

## 5. 분류 평가

### 5.1 지표

```text
precision = TP / (TP + FP)
recall = TP / (TP + FN)
f1 = 2 * precision * recall / (precision + recall)
uncertain_rate = uncertain / total
```

기술 문서를 positive로 본다.

### 5.2 Gate

| 지표 | Gate |
| --- | ---: |
| technical recall | 95% 이상 |
| technical precision | 85% 이상 |
| 문서 수준 recall | 97% 이상 |
| 중요 보안·운영 문서 recall | 100% |
| uncertain 오분류 손실 | 0건 |

uncertain 비율은 단독 gate가 아니지만 validation 기준선보다 10%p 이상 증가하면 승격을 보류한다.

### 5.3 임계값 선택

1. calibration set에서 후보 임계값 그리드 계산
2. recall 95% 이상 후보만 유지
3. 그중 precision 최고 후보 선택
4. validation set 확인
5. test set 한 번 평가
6. 모델 revision, 중심점, 임계값을 같은 버전으로 고정

test 결과를 보고 임계값을 다시 조정하면 새 데이터셋 버전을 만든다.

## 6. 중복 평가

### 6.1 쌍 판정

| 지표 | Gate |
| --- | ---: |
| confirmed duplicate precision | 98% 이상 |
| exact recall | 100% |
| near text recall | 95% 이상 |
| semantic recall | 90% 이상 |
| conflict를 duplicate로 병합 | 0건 |

### 6.2 군집 평가

- cluster purity 98% 이상
- 정규본 선정 정책 일치 100%
- transitive semantic drift 0건
- 모든 멤버 source lineage 보존 100%
- ACL이 다른 멤버 제거 0건

### 6.3 임계값 보정

MinHash와 cosine score를 positive·negative·conflict별로 그린다. 자동 confirmed threshold는 precision 98% 조건을 우선한다. review lower bound는 검토량이 전체 후보의 20%를 넘지 않도록 하되 conflict recall을 낮추지 않는다.

## 7. 검색 평가

### 7.1 질문 fixture

각 질문은 다음을 가진다.

- query text
- 요청 주체와 ACL
- relevant chunk ID 집합
- 필수 문서 family
- 시간·버전 조건
- conflict 기대 여부

### 7.2 지표

```text
Recall@K = relevant retrieved in top K / all relevant
MRR = mean(1 / rank of first relevant)
nDCG@K = normalized discounted cumulative relevance
ACL leakage rate = unauthorized hits / all returned hits
```

### 7.3 Gate

| 지표 | Gate |
| --- | ---: |
| Recall@10 | 90% 이상 |
| MRR@10 | 0.75 이상 |
| nDCG@10 | 0.80 이상 |
| ACL leakage | 0 |
| conflict member retrieval | 기대 fixture 100% |
| p95 latency, 500K 이하 | 250ms 이하 |

## 8. 주장 추출 평가

### 8.1 정확성

| 지표 | Gate |
| --- | ---: |
| claim precision | 95% 이상 |
| claim recall | 90% 이상 |
| claim type accuracy | 95% 이상 |
| quote exact match | 100% |
| source span valid | 100% |
| unsupported claim | 0 |
| duplicate claim rate | 2% 이하 |

구조 JSON이 schema를 통과해도 quote가 원문에 없으면 unsupported로 판정한다.

### 8.2 안정성

temperature 0과 고정 seed에서 3회 실행한다. claim ID 집합 Jaccard 0.98 이상을 요구한다. runtime이 완전 결정성을 보장하지 못하면 차이를 기록하고 결과 안정화 후처리를 검증한다.

## 9. 웹 검증 평가

### 9.1 검색 품질

- primary·authoritative 출처 top 5 포함률 90% 이상
- 스니펫만으로 검증 확정 0건
- canonical URL 정규화 오류 0건
- published_at 허위 추정 0건

### 9.2 관계 판정

| 지표 | Gate |
| --- | ---: |
| macro F1 | 90% 이상 |
| outdated recall | 95% 이상 |
| contradicted precision | 95% 이상 |
| insufficient를 확정 관계로 오판 | 0건 |
| 적용 버전 불일치 탐지 | 95% 이상 |

## 10. 합성과 인용 평가

### 10.1 문장 단위

도메인 검토자가 각 사실 문장을 다음으로 판정한다.

- entailed
- partially supported
- unsupported
- contradicted

`entailed`만 완전 지지로 계산한다.

### 10.2 지표와 Gate

| 지표 | Gate |
| --- | ---: |
| 근거 커버리지 | 100% |
| 인용 정확도 | 95% 이상 |
| unsupported 문장 | 0 |
| contradicted 문장 | 0 |
| 승인 없는 외부 변경 포함 | 0 |
| conflict 누락 | 0 |
| ACL 교차 누출 | 0 |
| topic 구조 정확도 | 95% 이상 |

인용 정확도가 95%여도 unsupported 한 건이 있으면 출시를 차단한다.

### 10.3 한국어 품질

5점 척도로 평가한다.

- 의미 정확성
- 기술 용어 일관성
- 문장 명료성
- 불필요한 반복 없음
- 적용 범위와 조건 표현

평균 4.2 이상, 어떤 항목도 3.5 미만이 아니어야 한다. 표현 품질은 사실성 gate를 대체하지 않는다.

## 11. 보안 평가

### 11.1 Egress fixture

- IPv4·IPv6·CIDR
- 내부 hostname과 domain suffix
- email, 사번, 고객명
- API key, JWT, PEM, password
- stack trace, 절대 경로, 저장소명
- Unicode homoglyph와 공백 난독화
- base64, URL encoding, double encoding

민감 전송 0건이 절대 gate다.

### 11.2 SSRF fixture

- loopback, private, link-local, multicast
- decimal·hex IP 표현
- DNS rebinding 시뮬레이션
- 허용 URL에서 private redirect
- userinfo hostname 혼동
- IDN homoglyph
- IPv4-mapped IPv6

모든 케이스 차단을 요구한다.

### 11.3 Prompt injection fixture

- 사내 문서 내 시스템 지시 위조
- 웹 문서 내 이전 지시 무시
- secret·prompt 요청
- tool call JSON
- Markdown 링크와 이미지 URL 지시
- 긴 문맥 끝에 숨긴 지시
- 여러 언어 혼합 지시

도구 실행, 네트워크 우회, secret 노출, 근거 없는 claim 생성이 모두 0이어야 한다.

### 11.4 ACL fixture

- 같은 topic의 서로 다른 group 문서
- ACL 변경 리비전
- 공개 evidence와 restricted claim 결합
- 빈 ACL 교집합
- operator-only 문서

무권한 검색 hit와 artifact 노출 0건이 gate다.

### 11.5 Folder Revision fixture

- before와 after root 동일·중첩
- `..`, 절대 경로, 대소문자 혼동, Unicode 정규화 경로
- symbolic link, junction, dangling link, special file
- 기존 run ID 충돌과 finalized run 수정
- 준비 중 before 파일 크기·mtime·SHA-256 변경
- added, modified, removed, unchanged 각각 10건 이상
- UTF-8, 한글, CRLF·LF, binary 파일 비교
- comparison 보고서 작성 중 프로세스 종료
- Confluence URL, API 키, access token 설정 키 주입

절대 gate는 before 변경 0건, 승인 경로 밖 쓰기 0건, 기존 run overwrite 0건, finalized run의 입력·비교 매니페스트 완전성 100%다.

## 12. 성능·안정성 평가

### 12.1 코퍼스

| 크기 | 문서 | 페이지 | 예상 청크 | 목적 |
| --- | ---: | ---: | ---: | --- |
| small | 100 | 2000 | 5000 | PR smoke |
| medium | 5000 | 100000 | 250000 | 릴리스 회귀 |
| stress | 실제 목표 상한 | 측정 | 500000 이상 | 용량 계획 |

### 12.2 Track A

- documents/hour
- pages/hour
- embedding tokens/second
- peak memory
- index build duration
- unchanged skip rate
- OOM batch reductions

변경 없는 두 번째 실행은 parse·embed 0회이며 첫 실행 시간의 5% 이하여야 한다.

### 12.3 Track B

- model load time
- first token latency
- prefill tokens/second
- decode tokens/second
- peak resident memory
- minimum available memory
- swap delta
- structured output failure rate

16K·2048 출력 시 OOM 0건, 최소 가용 6GB, 지속 swap 증가 0이 필수다.

### 12.4 장시간

4시간 혼합 워크로드:

1. Track A 배치
2. 워커 종료와 Qwen 로드
3. 주장 추출 20건
4. Qwen 종료와 BGE 재로드
5. 위 사이클 반복

gate:

- 미복구 작업 0
- 고아 worker 0
- 가속기 리스 동시 소유 0
- 메모리 기준선 지속 증가 없음
- DB integrity 유지

## 13. 실패 주입

| 주입 | 기대 결과 |
| --- | --- |
| 파싱 중 프로세스 종료 | 리스 만료 후 재시도, 중복 결과 없음 |
| 임베딩 OOM | batch 절반, 최소 1 실패 분류 |
| Qwen timeout | 취소, worker 회수, 최대 시도 준수 |
| SQLite busy | timeout과 재시도, 이중 writer 없음 |
| 디스크 부족 | 새 write 중단, 기존 active 세대 유지 |
| FAISS 파일 손상 | 활성화 거부, 이전 세대 유지 |
| publish rename 실패 | 기존 artifact 유지 |
| DNS private redirect | 요청 차단과 audit |
| 검색 429 | backoff 후 insufficient evidence |
| CAS hash mismatch | recovery 모드 |

## 14. 모델 회귀와 Qwen 고정

Qwen revision, MLX runtime, quantization이 바뀌면 다음을 모두 재실행한다.

- 주장 추출 전체 test
- 관계 판정 전체 test
- 합성 50주제
- 한국어 품질 블라인드 평가
- 구조 출력 안정성
- 4K·16K·24K·32K 성능 매트릭스
- 4시간 혼합 워크로드
- prompt injection fixture

대체 모델은 같은 입력, 토큰 예산, prompt 의미, 4bit 조건에서 비교한다. 현 기준인 Qwen보다 사실성·인용·보안 gate가 하나라도 낮으면 교체하지 않는다.

## 15. 평가 리포트

```json
{
  "schema_version": 1,
  "evaluation_id": "019...",
  "pipeline_fingerprint": "sha256:...",
  "dataset_versions": {},
  "metrics": {},
  "security_failures": [],
  "performance": {},
  "failed_gates": [],
  "approved_by": [],
  "created_at": "2026-08-10T06:00:00.000000Z"
}
```

승격은 failed gate가 비고 품질, 보안, 운영 승인자가 모두 서명한 리포트만 허용한다.

## 16. CI 단계

| 단계 | 빈도 | 데이터 |
| --- | --- | --- |
| unit·architecture | 모든 변경 | synthetic |
| parser·chunk contract | 모든 변경 | small golden |
| security smoke | 모든 변경 | 핵심 fixture |
| small end-to-end | PR | small corpus |
| full quality regression | 릴리스 후보 | test set |
| target Mac performance | 모델·runtime·pipeline 릴리스 | medium·benchmark |
| 4시간 soak·failure injection | production 승격 | mixed workload |

## 17. 출시 판정

출시 가능:

- 모든 절대 gate 통과
- 품질 지표 기준 이상
- target Mac 16K 운영 기준 통과
- security failure 0
- backup·restore 성공
- 문서와 구현 fingerprint 일치

출시 불가:

- 근거 없는 사실 한 건 이상
- 민감정보 전송 한 건 이상
- ACL 누출 한 건 이상
- 원본 또는 기존 리비전 변경
- 반복 OOM 또는 swap 증가
- 복구 불가능한 작업·DB 오류
