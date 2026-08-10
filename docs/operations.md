<!-- docs/operations.md -->
# 운영·배포·백업·장애 대응 가이드

## 1. 운영 전제

- 대상 호스트: MacBook Pro M4 Max, 통합 메모리 36GB
- macOS 15 이상
- Python 3.12
- 로컬 단일 호스트 배포
- Qwen 작업 동시성 1
- BGE와 Qwen 가속기 동시 적재 금지
- 외부 검색 기본 비활성
- 원본 source root 읽기 전용

운영값은 대상 장비의 Milestone 0 벤치마크 결과로 확정한다. 벤치마크 없이 24K 또는 32K 컨텍스트를 production에 설정하지 않는다.

## 2. 설치 산출물

```text
install/
├── application/
├── config/
├── models/
│   ├── qwen/
│   └── bge/
├── manifests/
│   ├── build.json
│   ├── dependencies.json
│   └── models.json
└── var-link
```

`models.json`은 model ID, immutable revision, 변환 runtime, 파일 목록, 크기, SHA-256, 라이선스를 포함한다.

## 3. 최초 설치 순서

1. macOS와 사용 가능 통합 메모리 확인
2. APFS 여유 공간 확인
3. 전용 OS 사용자, `data/before`, `data/after`, `var_root` 생성
4. Python 3.12와 `uv` 확인
5. lockfile 기반 의존성 설치
6. 모델 파일 다운로드와 해시 검증
7. 웹 검색을 활성화하는 환경에서만 Tavily Keychain secret 등록
8. `config/production.yaml` 생성과 스키마 검사
9. SQLite 초기 migration
10. `rag doctor` 실행
11. Milestone 0 벤치마크 실행
12. 승인된 설정 반영
13. 작은 골든 코퍼스로 end-to-end dry run
14. 백업과 빈 디렉터리 복구 시험

## 4. `rag doctor` 검사

| 검사 | 실패 등급 |
| --- | --- |
| Python·macOS 지원 버전 | fatal |
| 설정 스키마와 경로 | fatal |
| source와 var root 겹침 | fatal |
| before·after·var root 비중첩 | fatal |
| before read-only와 after 신규 run write | fatal |
| before/after link·junction 없음 | fatal |
| SQLite open, WAL, foreign key | fatal |
| CAS write·read·hash·delete 임시 객체 | fatal |
| 모델 manifest와 파일 hash | fatal |
| BGE descriptor와 출력 차원 | fatal |
| Qwen 최소 32토큰 생성 | fatal |
| Tavily Keychain secret 존재 | 웹 활성일 때만 fatal |
| Confluence 금지 설정 키 부재 | fatal |
| 외부 웹 disabled 차단 | fatal |
| FAISS smoke index build·search | fatal |
| artifact 임시 세대 활성화·롤백 | fatal |
| 로그 디렉터리 회전 가능 | warning |
| 디스크 권장 여유 | warning |

doctor는 production 데이터와 활성 세대를 변경하지 않고 별도 staging에서 수행한다.

## 5. 하드웨어 벤치마크

### 5.1 사전 조건

- AC 전원 연결
- Low Power Mode 비활성
- 다른 고메모리 앱 종료
- 동일 실내 환경에서 반복
- 모델 해시와 설정 스냅샷 기록
- warm-up 1회 후 측정 3회

### 5.2 Qwen 매트릭스

| 컨텍스트 | 출력 | 반복 |
| ---: | ---: | ---: |
| 4K | 512 | 3 |
| 16K | 512 | 3 |
| 16K | 2048 | 3 |
| 24K | 512 | 3 |
| 24K | 2048 | 3 |
| 32K | 512 | 3 |
| 32K | 2048 | 3 |

측정값은 model load, prefill, first token, decode tokens/sec, total duration, peak resident memory, minimum available memory, swap delta, memory pressure, thermal state다.

### 5.3 BGE 매트릭스

길이 512와 1024토큰, batch 4·8·16을 조합한다. 문서/초, 토큰/초, peak memory, OOM과 자동 batch 축소를 기록한다.

### 5.4 승격 규칙

- 16K는 필수 통과 대상이다.
- 24K와 32K는 각 최악 출력 조건에서 가용 메모리 6GB 이상, 지속 swap 증가 없음, 비정상 종료 없음, 품질 회귀 없음일 때만 허용한다.
- 세 번 중 한 번이라도 memory critical이면 해당 컨텍스트는 불합격이다.
- p95가 아니라 최악값으로 메모리 안전을 판단한다.

### 5.5 벤치마크 결과 스키마

```json
{
  "schema_version": 1,
  "benchmark_id": "019...",
  "host": {
    "model": "MacBook Pro M4 Max",
    "unified_memory_gib": 36,
    "macos_version": "string"
  },
  "model_manifest_sha256": "64-hex",
  "config_sha256": "64-hex",
  "scenario": {
    "model": "qwen",
    "input_tokens": 16384,
    "max_output_tokens": 2048,
    "batch_size": 1
  },
  "metrics": {
    "load_ms": 0,
    "first_token_ms": 0,
    "decode_tokens_per_second": 0.0,
    "peak_resident_mib": 0,
    "minimum_available_mib": 0,
    "swap_delta_mib": 0,
    "thermal_state": "nominal"
  },
  "passed": true
}
```

## 6. 일상 실행

### 6.1 시작

```text
rag doctor --quick
rag serve --config config/production.yaml
rag run status --latest
```

시작 순서:

1. 설정과 model manifest 검증
2. SQLite migration 상태 검증
3. 이전 비정상 작업과 리스 회수
4. 활성 FAISS·artifact 세대 검증
5. Coordinator ready
6. 워커는 작업이 들어올 때 지연 시작

### 6.2 증분 인제스천

```text
rag revision prepare --run-id <revision-run-id>
rag ingest --source before-folder --revision-run <revision-run-id>
rag run status <run-id> --watch
```

완료 후 확인:

- discovered, changed, skipped, quarantined 수
- parse와 embedding 실패
- classification uncertain 비율
- 새 vector generation ID와 smoke 결과
- 메모리 pressure 이벤트
- 입력 매니페스트 파일 수와 before SHA-256 재검증

### 6.3 검증과 합성

```text
rag validate --source-run <run-id>
rag review list --status pending
rag synthesize --taxonomy-version <version>
rag publish --generation <generation-id> --revision-run <revision-run-id>
rag revision compare --run-id <revision-run-id>
rag revision finalize --run-id <revision-run-id>
```

게시 전 `citation coverage=1.0`, 미결 필수 승인 0, artifact manifest, before 해시 불변, comparison report 검증을 확인한다.

### 6.4 안전 종료

```text
rag shutdown --grace-seconds 60
```

Coordinator는 새 작업 수락을 중지하고, 실행 중 작업에 취소를 전달하고, SQLite 커밋·WAL 체크포인트·워커 종료 순서로 닫는다. 유예를 넘긴 워커만 강제 종료한다.

## 7. 상태와 메트릭

### 7.1 핵심 운영 대시보드

| 메트릭 | 정상 | 경고 | 심각 |
| --- | --- | --- | --- |
| 가용 메모리 | 8GB 이상 | 6GB 미만 | 3GB 미만 |
| swap 증가 | 안정 | 256MiB/분 이상 | 512MiB/분 이상 |
| Qwen first token | 기준선 +20% 이내 | +50% | +100% |
| Qwen decode | 기준선 -20% 이내 | -40% | -60% |
| job oldest ready age | 5분 미만 | 30분 | 2시간 |
| worker heartbeat | 정상 | 1회 누락 | 3회 누락 |
| parse failure | 1% 미만 | 3% | 10% |
| uncertain 비율 | 평가 기준 ±5%p | +10%p | +20%p |
| citation failure | 0 | 1건 | 반복 발생 |
| 외부 query block | 기준선 | 급증 | 허용 후 민감 탐지 |
| disk free | 25% 이상 | 15% | 10% |

품질 지표 변동은 코퍼스 변화일 수 있으므로 자동 설정 변경이 아니라 검토를 유발한다.

### 7.2 헬스 상태

| 상태 | 의미 |
| --- | --- |
| `healthy` | DB·CAS·활성 세대 정상, critical alert 없음 |
| `degraded` | 일부 source, 웹, worker가 비정상이지만 안전한 기능 가능 |
| `read_only` | 무결성 또는 디스크 위험으로 새 쓰기 차단 |
| `recovery` | 복구·검증 외 작업 금지 |
| `stopping` | 안전 종료 중 |

## 8. 백업

### 8.1 백업 전 조건

- 새 publish와 index activation 잠금
- 진행 중 SQLite transaction 종료 대기
- 활성 vector·artifact 세대 ID 고정
- CAS garbage collection 중지

### 8.2 절차

1. backup ID 생성
2. SQLite online backup API로 사본 생성
3. `PRAGMA integrity_check`와 `foreign_key_check`
4. 활성 FAISS 세대 복사와 체크섬
5. 활성 artifact 세대 복사와 체크섬
6. DB 참조 CAS object 목록 생성
7. CAS 객체 존재·해시 검사
8. 설정과 model manifest 복사
9. 참조 중인 before 입력 매니페스트와 finalized after run 복사
10. 전체 backup manifest 생성
11. 임시 백업 디렉터리를 원자적으로 완료 상태로 변경

### 8.3 백업 합격 기준

- SQLite integrity `ok`
- foreign key 위반 0
- 누락 CAS 객체 0
- 활성 FAISS vector count와 DB member count 일치
- artifact evidence manifest 검증 성공
- 모든 파일 hash 일치
- finalized run의 comparison hash와 documents hash 일치

## 9. 복구

### 9.1 빈 호스트 복구

1. 애플리케이션과 동일 build 설치
2. 모델 파일 재설치와 manifest 검증
3. 백업을 새 `var_root.restore`에 풀기
4. backup manifest 전체 검증
5. SQLite read-only open과 integrity 검사
6. CAS reference 검사
7. FAISS smoke query
8. artifact citation manifest 검사
9. finalized after run의 비교 매니페스트 검사
10. Coordinator를 read-only로 시작
11. 운영자 승인 후 활성 `var_root` 교체
12. 작은 증분 ingest 실행

### 9.2 롤백

- 모델·코드 롤백은 이전 build와 호환 DB backup을 함께 사용한다.
- vector index는 최근 verified retired 세대로 활성화할 수 있다.
- artifact는 최근 approved retired 세대로 활성화할 수 있다.
- 새 schema를 이전 binary가 읽을 수 있다고 가정하지 않는다.

## 10. 모델 업그레이드

1. 새 model revision과 파일 hash를 staging manifest에 추가
2. 격리 설치와 최소 생성 검사
3. 고정 평가 세트 전체 실행
4. 메모리·처리량 매트릭스 실행
5. 구조 출력과 citation 품질 비교
6. 새 pipeline fingerprint로 shadow 실행
7. 품질·성능·보안 승인
8. production 설정 revision 변경
9. 점진적으로 신규 실행에만 적용
10. 회귀 시 이전 revision과 이전 결과 세대 유지

기존 claim과 artifact를 덮어쓰지 않는다. 새 모델 결과는 새 fingerprint로 병렬 저장한다.

## 11. 장애 대응 Runbook

### 11.1 메모리 압박

증상:

- `PRESSURE` 또는 `CRITICAL`
- swap 지속 증가
- 모델 decode 급락

조치:

1. 새 Track A·B 작업 수락 중지
2. BGE batch 자동 축소 확인
3. 실행 중 모델 작업 안전 취소
4. worker 종료와 메모리 회수 확인
5. Coordinator·DB 일관성 검사
6. context와 batch를 마지막 승인값으로 복원
7. 반복 시 해당 실행 입력 크기와 모델 revision 분석

### 11.2 Track B 워커 무응답

1. heartbeat 3회 누락 확인
2. cancel 전송
3. 15초 대기
4. worker 강제 종료
5. 가속기 리스 만료
6. RUNNING job을 retry wait로 회수
7. staging 결과 비정본 처리
8. 세 번째 반복에서 job 실패와 운영 알림

### 11.3 SQLite 잠금·무결성

잠금:

1. 단일 writer 위반 프로세스 확인
2. 새 작업 중지
3. busy timeout 후 실패 job 회수
4. worker의 직접 DB 쓰기 여부 조사

무결성:

1. 즉시 read-only 또는 recovery
2. WAL과 DB 보존
3. integrity·foreign key 검사
4. 검증 백업 복구
5. 원인 확인 전 쓰기 재개 금지

### 11.4 FAISS 세대 오류

1. 새 세대 활성화 중지
2. 현재 active checksum과 vector count 검사
3. 손상 시 최근 verified retired 세대 활성화
4. DB embedding record에서 새 세대 재빌드
5. smoke query 결과 비교

### 11.5 citation failure 급증

1. publish 차단 확인
2. prompt, parser, chunker, verifier 변경 이력 확인
3. 실패 문장 유형별 샘플링
4. 근거 quote 역매핑 검사
5. 원인 단계만 새 fingerprint로 재실행
6. 회귀 fixture 추가

### 11.6 외부 검색 장애

- 내부 전용 검증을 계속할 수 있다.
- 외부 결과가 필수인 job은 retry wait 후 `insufficient_evidence`다.
- 공급자 장애 때문에 허용 도메인이나 보안 검사를 완화하지 않는다.

## 12. 유지보수

| 작업 | 주기 | 검증 |
| --- | --- | --- |
| SQLite backup | 매일 | 매일 자동 검증 |
| 전체 복구 훈련 | 월 1회 | 빈 디렉터리 복구 |
| CAS reference audit | 주 1회 | 누락·고아 리포트 |
| retired index 정리 | 월 1회 | dry run 후 최근 3개 보존 |
| retired artifact 정리 | 월 1회 | 최근 10개와 승인 참조 보존 |
| 모델 manifest 검사 | 시작 시, 주 1회 | 전체 hash |
| 보안 fixture | 릴리스마다 | 누출 0 |
| 품질 회귀 | 릴리스마다 | 모든 gate |
| 성능 기준선 | 모델·runtime 변경 시 | 대상 Mac 전체 매트릭스 |

## 13. 운영 완료 체크리스트

- production 설정과 fingerprint 보관
- model·dependency manifest 해시 일치
- 16K 성능·메모리 gate 통과
- before read-only, after 신규 run write, var path 분리
- 웹 disabled 확인 또는 egress 승인 확인
- Tavily Keychain secret 노출과 Confluence 자격정보 부재 검사
- before 해시 불변과 finalized run overwrite 차단 검사
- 골든 코퍼스 end-to-end 통과
- backup 생성과 복구 통과
- 알림 수신 경로 시험
- 롤백할 이전 build·DB·index·artifact 확보
