<!-- README.md -->
# Enterprise Document RAG

## GUI 바로 실행

프로젝트 루트에서 다음 명령을 실행하면 됩니다.

```bash
venv/bin/python main.py
```

Windows 가상환경에서는 `venv\Scripts\python.exe main.py`를 사용합니다. `main.py`는 현재
작업 디렉터리와 editable 설치 여부에 관계없이 이 프로젝트의 `src`와 설정을 사용해 GUI를
시작합니다.

로컬 우선 사내 문서 처리 시스템입니다. 외부 원본 시스템의 자격정보를 AI에 전달하지 않고, `data/before`의 불변 입력과 `data/after/runs/<run_id>`의 실행별 수정본을 분리합니다.

## 개발 환경

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements-mlx.txt
python -m pip install -r requirements-gui.txt
python -m pip install -e .
```

`requirements-mlx.txt`는 Apple Silicon용 로컬 추론 런타임입니다. 통합 명령을 처음 실행하면
설정에 고정된 `mlx-community/Qwen3.6-27B-4bit` 모델 리비전(약 16.1GB)을 Hugging Face
캐시에 자동으로 다운로드합니다.

## 초기 명령

```bash
rag doctor
rag revision prepare --run-id 20260810t120000z-oracle
rag revision compare --run-id 20260810t120000z-oracle
rag revision finalize --run-id 20260810t120000z-oracle
```

## 전체 문서 자동 통합

다음 명령은 기존 호환 경로입니다. `data/before`의 지원되는 모든 UTF-8 텍스트 문서를 읽고,
로컬 Qwen 모델로 계층형 통합 문서를 생성한 뒤 새 run과 비교 보고서를 작성합니다.

```bash
rag document integrate
```

이 명령은 기존 호환 map/reduce 경로입니다. 신규 Job 경로는 Evidence·Claim·Task
품질 게이트와 결정적 조립, 게시 run까지 연결됐지만 실제 27B 전체 품질·용량
평가를 통과하기 전에는 운영 정본으로 확정하지 않습니다. 현재 상태는
[구현 상태](docs/implementation-status.md)를 기준으로 합니다.

실행 중에는 문서 탐색, 청크 분할, 모델 로딩, 생성 배치, 저장 및 비교 단계가
`[ 45%] 통합 문서를 생성하는 중 (2/8)` 형식으로 표시됩니다. 최종 JSON 결과는 기존과
동일하게 표준 출력으로 제공되므로 리다이렉션이나 스크립트 연동에도 영향을 주지 않습니다.

실행 결과는 자동 생성된
`data/after/runs/<run_id>/documents/integrated-technical-guide.md`에 저장됩니다. 원본 복사본과
통합 문서를 검토한 뒤 확정합니다.

```bash
rag revision finalize --run-id <결과에 표시된 run_id>
```

run ID와 출력 파일명을 직접 지정할 수도 있습니다.

```bash
rag document integrate \
  --run-id 20260811t120000z-company-guide \
  --output company-technical-guide.md
```

지원 입력 형식은 `.md`, `.txt`, `.rst`, `.html`, `.csv`, `.json`, `.yaml`, `.yml`,
`.toml`, `.ini`, `.xml`입니다. `data/before`는 변경하지 않으며 모델에는 파일·셸·도구 실행
권한을 부여하지 않습니다.

## 데스크톱 GUI

기존 Application 구조에 통합된 독립 PySide6 프로그램을 실행합니다.

```bash
rag-gui --project-root .
```

메인 화면은 `실행`과 `설정` 탭으로 구성됩니다. 설정 탭은 원본·결과 폴더, 로컬 cache 또는
Hugging Face 최신 MLX 모델 검색, 고정 commit revision, 모델 크기·양자화·context·라이선스·
장비 적합성, 사용자 추가 시스템 지침과 실행 정책을 관리합니다. 원격 검색은 오프라인 모드를
명시적으로 해제한 경우에만 실행됩니다. 원격 모델 다운로드는 예상 전송량과 5GiB 안전 여유를
더한 디스크 사전 검사, 파일·바이트 진행률과 취소, exact commit snapshot 재검증을 제공합니다.
검증이 끝난 모델만 Job에 사용할 수 있습니다. 실행 탭은 Job 생성·취소, 전체 진행률, 단계 이벤트,
검증된 체크포인트와 Worker PID·heartbeat·건강 상태를 표시합니다. 별도 `LLM 실시간 스트림` 탭은
현재 생성 단계와 검증 전 문자열을 로컬 append-only 로그에서 약 2초 간격으로 갱신합니다. Claim
추출은 Evidence별 체크포인트 건수와 30~39% 구간 진행률을 표시하므로 장시간 단계도 정지처럼
보이지 않으며, 실패·취소 후에는 저장된 다음 Evidence부터 재개합니다. 게시가 끝나면 최종 문서,
품질 JSON, 비교 Markdown과 합성 보고서를 검증된 절대 경로로 열 수 있고 Task·Claim·Evidence
coverage와 추가·수정·삭제·동일 건수를 함께 확인할 수 있습니다.
주요 작업과 상태, 결과·품질, 실행 상세를 정보 중요도 순으로 분리했으며 작은 화면에서는
카드 내용을 압축하지 않고 수직 스크롤로 확인합니다.

Job을 생성한 뒤 `파이프라인 시작/재개`를 누르면 GUI와 분리된 로컬 실행 프로세스가
고정 10단계를 수행합니다. 프로세스 소유권은 Job별 파일 lock과 runner token으로 보호하고,
heartbeat가 3회 누락되면 GUI가 `STALE`로 표시합니다. Job 생성 전에 선택 모델의 정확한 commit,
로컬 cache와 장비 적합성을 다시 검증합니다. Worker 사전 점검은 결과 루트를 즉시 생성하지만
`runs/<job_id>` 게시 산출물은 최종 품질 게이트 통과 전에는 만들지 않습니다. `즉시 취소 요청`은 Worker에 `SIGTERM`을 보내고
MLX 생성 스트림을 다음 토큰 경계에서 중단합니다. 체크포인트를 닫는 정상 종료를 15초 기다린 뒤에도
남은 Worker만 강제 종료합니다. 완료 알림 정책이 켜진 Job은 게시 해시 기반 영수증을 먼저
선점한 뒤 macOS 알림을 한 번만 시도하며 전달·실패·불확실 상태를 실행 탭에 표시합니다.

## Document Job 관리

GUI와 새 파이프라인이 공유할 SQLite Job 경계는 CLI에서 먼저 사용할 수 있습니다.

```bash
rag job create \
  --source-root /absolute/path/to/source \
  --instruction "중복을 통합하고 운영 절차와 충돌을 보존해 기술 문서를 작성" \
  --output integrated-technical-guide.md
rag job list
rag job status --job-id <job_id>
rag job start --job-id <job_id>
rag job events --job-id <job_id> --after-sequence 0
rag job cancel --job-id <job_id>
```

`job create`는 정의와 체크포인트를 만들고 `job start`가 별도 로컬 Worker를 시작합니다.
오프라인 모드에서는 선택한 Hugging Face commit이 로컬 캐시에 있어야 하며, 없으면
네트워크를 시도하지 않고 작업을 안전하게 실패 처리합니다.

상세 설계는 [문서 인덱스](docs/README.md)와 [구현 계획](IMPLEMENTATION_PLAN.md)을 기준으로 합니다.
