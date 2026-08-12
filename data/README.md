<!-- data/README.md -->
# 문서 리비전 데이터 작업공간

이 디렉터리는 원본 시스템 자격정보 없이 파일만으로 문서를 입력·수정·비교하기 위한 경계다.

## 디렉터리 역할

| 경로 | 역할 | AI 권한 |
| --- | --- | --- |
| `before/` | 데이터 관리자가 배치한 수정 전 스냅샷 | 읽기만 허용 |
| `after/runs/<run_id>/documents/` | 신규 실행의 수정 후 문서 | 해당 실행 finalization 전 읽기·신규 쓰기 허용 |
| `after/runs/<run_id>/_reports/` | 입력 매니페스트, 비교 결과, unified diff | 준비·비교 도구만 쓰기 허용 |

Worker는 시작 시 `after/` 루트가 없으면 생성해 링크·중첩·쓰기 경계를 먼저 검증한다. 이때
`runs/<run_id>`이나 결과 파일은 만들지 않으며, 검증된 최종 품질 게이트를 통과한 게시 단계에서만
신규 run을 원자적으로 노출한다.

Confluence를 포함한 원본 시스템 내보내기는 이 경계 밖에서 수행한다. AI에는 Confluence API 키, access token, cookie, 로그인 세션을 제공하지 않는다.

## 처리 흐름

```text
외부 승인 내보내기
    -> data/before 불변 스냅샷
    -> 신규 data/after run 준비
    -> run의 documents만 수정
    -> 파일별 해시와 텍스트 diff 생성
    -> finalization
    -> 사람 검토와 별도 게시
```

운영 절차와 강제 권한은 [문서 리비전 스킬](../skills/manage-document-revisions/SKILL.md) 및 [권한 모델](../skills/manage-document-revisions/references/permission-model.md)을 따른다.
