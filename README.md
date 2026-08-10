<!-- README.md -->
# Enterprise Document RAG

로컬 우선 사내 문서 처리 시스템입니다. 외부 원본 시스템의 자격정보를 AI에 전달하지 않고, `data/before`의 불변 입력과 `data/after/runs/<run_id>`의 실행별 수정본을 분리합니다.

## 개발 환경

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pip install -e .
```

## 초기 명령

```bash
rag doctor
rag revision prepare --run-id 20260810t120000z-oracle
rag revision compare --run-id 20260810t120000z-oracle
rag revision finalize --run-id 20260810t120000z-oracle
```

상세 설계는 [문서 인덱스](docs/README.md)와 [구현 계획](IMPLEMENTATION_PLAN.md)을 기준으로 합니다.
