<!-- README.md -->
# Enterprise Document RAG

로컬 우선 사내 문서 처리 시스템입니다. 외부 원본 시스템의 자격정보를 AI에 전달하지 않고, `data/before`의 불변 입력과 `data/after/runs/<run_id>`의 실행별 수정본을 분리합니다.

## 개발 환경

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements-mlx.txt
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

다음 명령 하나가 `data/before`의 지원되는 모든 UTF-8 텍스트 문서를 읽고, 새 run을 만든 뒤,
로컬 Qwen 모델로 계층형 통합 문서를 생성하고 비교 보고서까지 작성합니다.

```bash
rag document integrate
```

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

상세 설계는 [문서 인덱스](docs/README.md)와 [구현 계획](IMPLEMENTATION_PLAN.md)을 기준으로 합니다.
