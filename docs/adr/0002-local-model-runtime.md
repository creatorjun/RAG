<!-- docs/adr/0002-local-model-runtime.md -->
# ADR-0002: Qwen MLX 로컬 런타임과 분리 워커

- 상태: Accepted
- 기준일: 2026-08-10

## Context

대상 장비는 M4 Max 통합 메모리 36GB다. 기준 모델은 `mlx-community/Qwen3.6-27B-4bit`이고 BGE-M3도 로컬에서 실행한다. 두 모델을 같은 Python 프로세스에 장기 적재하면 메모리 압박과 Metal allocator 잔존으로 안정적인 16~32K 처리가 어려울 수 있다.

## Decision

- Qwen은 MLX 기반 4bit 모델을 사용한다.
- 텍스트 작업의 최종 runtime은 Milestone 0에서 `mlx-vlm`을 우선 검증하고 `mlx-lm` 호환 경로를 비교해 고정한다.
- Coordinator는 MLX와 BGE 모델을 로드하지 않는다.
- Track A와 Track B를 별도 worker process로 실행한다.
- `ACCELERATOR_TRACK_A`와 `ACCELERATOR_TRACK_B` 리스는 상호 배타다.
- Qwen 생성 동시성은 1이다.
- 운영 기본 context는 16K다.
- 24K와 32K는 대상 장비 성능 gate를 통과한 경우에만 허용한다.
- worker 프로세스 종료를 모델 메모리 회수의 최종 수단으로 사용한다.

## Runtime Acceptance

- 16K 입력과 2048 출력에서 OOM 0
- 최소 가용 메모리 6GB
- 지속 swap 증가 0
- worker 종료 후 다음 모델 load 성공
- 구조 출력 schema 성공
- 취소 15초 안에 완료 또는 프로세스 회수

## Consequences

장점:

- 모델 메모리와 실패를 Coordinator에서 격리한다.
- 프로세스 종료로 메모리 회수를 보장한다.
- 모델 runtime을 포트 뒤에서 교체할 수 있다.

비용:

- IPC와 worker lifecycle 구현이 필요하다.
- 모델 전환마다 load latency가 발생한다.
- prompt cache를 프로세스 종료 사이 재사용하기 어렵다.

## Rejected Alternatives

### PyTorch 기본 runtime

Apple Silicon 대상 메모리와 추론 효율을 위해 기본 선택에서 제외한다. BGE adapter는 공식 지원과 실측에 따라 PyTorch/MPS를 사용할 수 있지만 Qwen 메인 runtime에는 사용하지 않는다.

### 두 모델 동시 상주

처리량은 개선될 수 있으나 36GB의 안전 여유와 32K 확장 가능성을 줄이므로 기본 운영에서 거부한다.

### 같은 프로세스에서 모델 unload

가비지 수집과 runtime cache에 의존해 메모리 회수가 불확실하므로 최종 안전 보증으로 사용하지 않는다.
