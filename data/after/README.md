<!-- data/after/README.md -->
# 수정 후 문서 저장소

모든 수정 결과는 기존 실행을 덮어쓰지 않고 `runs/<run_id>`에 새로 만든다.

## 실행 구조

```text
after/
└── runs/
    └── <run_id>/
        ├── documents/
        ├── _reports/
        │   ├── input-manifest.json
        │   ├── comparison.json
        │   ├── comparison.md
        │   └── diffs/
        └── run-manifest.json
```

`documents/`는 수정 전 트리의 상대 경로를 보존한다. `_reports/`는 도구 전용이며 수동 편집하지 않는다. `run-manifest.json`의 상태가 `finalized`가 된 실행은 불변으로 취급하고, 추가 수정이 필요하면 새 run을 만든다.
