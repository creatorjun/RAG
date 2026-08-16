# src/enterprise_rag/domain/errors.py
from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

JsonScalar = str | int | float | bool | None


class ErrorCategory(str, Enum):
    TRANSIENT_SOURCE = "TRANSIENT_SOURCE"
    TRANSIENT_NETWORK = "TRANSIENT_NETWORK"
    RESOURCE_PRESSURE = "RESOURCE_PRESSURE"
    INVALID_INPUT = "INVALID_INPUT"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    DATA_CORRUPTION = "DATA_CORRUPTION"
    SECURITY_BLOCK = "SECURITY_BLOCK"
    MODEL_OUTPUT = "MODEL_OUTPUT"
    CONSISTENCY = "CONSISTENCY"
    CANCELLED = "CANCELLED"
    INTERNAL = "INTERNAL"


class ApplicationError(Exception):
    def __init__(
        self,
        code: str,
        category: ErrorCategory,
        retryable: bool,
        safe_message: str,
        context: Mapping[str, JsonScalar] | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.category = category
        self.retryable = retryable
        self.safe_message = safe_message
        self.context = dict(context or {})


_REVISION_ERROR_SPECS: dict[str, tuple[ErrorCategory, str]] = {
    "BEFORE_ROOT_NOT_READABLE": (
        ErrorCategory.SECURITY_BLOCK,
        "수정 전 문서 폴더를 읽을 수 없습니다.",
    ),
    "BEFORE_ROOT_MUTABLE": (
        ErrorCategory.SECURITY_BLOCK,
        "수정 전 문서 폴더가 읽기 전용이 아닙니다.",
    ),
    "BEFORE_AFTER_OVERLAP": (ErrorCategory.SECURITY_BLOCK, "수정 전후 문서 폴더가 겹칩니다."),
    "PATH_ESCAPE": (ErrorCategory.SECURITY_BLOCK, "허용된 문서 폴더를 벗어나는 경로입니다."),
    "LINK_NOT_ALLOWED": (
        ErrorCategory.SECURITY_BLOCK,
        "심볼릭 링크나 재분석 지점은 허용되지 않습니다.",
    ),
    "RUN_ALREADY_EXISTS": (ErrorCategory.INVALID_INPUT, "같은 실행 ID가 이미 존재합니다."),
    "RUN_NOT_FOUND": (ErrorCategory.INVALID_INPUT, "문서 리비전 실행을 찾을 수 없습니다."),
    "RUN_FINALIZED": (
        ErrorCategory.INVALID_INPUT,
        "완료된 실행은 변경하거나 다시 비교할 수 없습니다.",
    ),
    "INVALID_RUN_ID": (ErrorCategory.INVALID_INPUT, "실행 ID 형식이 올바르지 않습니다."),
    "INVALID_JOB_ID": (ErrorCategory.INVALID_INPUT, "문서 작업 ID 형식이 올바르지 않습니다."),
    "JOB_ALREADY_EXISTS": (ErrorCategory.INVALID_INPUT, "같은 문서 작업이 이미 존재합니다."),
    "JOB_NOT_FOUND": (ErrorCategory.INVALID_INPUT, "문서 작업을 찾을 수 없습니다."),
    "JOB_STATE_CONFLICT": (
        ErrorCategory.CONSISTENCY,
        "문서 작업 상태가 예상 상태와 일치하지 않습니다.",
    ),
    "PROGRESS_EVENT_CONFLICT": (
        ErrorCategory.CONSISTENCY,
        "문서 작업 진행 이벤트의 순서가 올바르지 않습니다.",
    ),
    "DATABASE_SCHEMA_INVALID": (
        ErrorCategory.CONSISTENCY,
        "메타데이터 데이터베이스 스키마가 올바르지 않습니다.",
    ),
    "JOB_ARTIFACT_ALREADY_EXISTS": (
        ErrorCategory.CONSISTENCY,
        "같은 문서 작업 산출물이 이미 존재합니다.",
    ),
    "JOB_ARTIFACT_NOT_FOUND": (
        ErrorCategory.INVALID_INPUT,
        "문서 작업 산출물을 찾을 수 없습니다.",
    ),
    "INPUT_HASH_CHANGED": (ErrorCategory.CONSISTENCY, "수정 전 문서가 실행 도중 변경되었습니다."),
    "COMPARISON_INCOMPLETE": (ErrorCategory.CONSISTENCY, "비교 보고서가 없거나 완전하지 않습니다."),
    "CONFIG_INVALID": (ErrorCategory.INVALID_INPUT, "프로젝트 설정이 올바르지 않습니다."),
    "INVALID_INPUT": (ErrorCategory.INVALID_INPUT, "입력값이 올바르지 않습니다."),
    "DESKTOP_SETTINGS_INVALID": (
        ErrorCategory.INVALID_INPUT,
        "데스크톱 설정 파일이 올바르지 않습니다.",
    ),
    "SETTINGS_REVISION_CONFLICT": (
        ErrorCategory.CONSISTENCY,
        "다른 창에서 설정이 변경되었습니다. 설정을 다시 불러오십시오.",
    ),
    "DEPENDENCY_MISSING": (ErrorCategory.INTERNAL, "필수 Python 의존성이 설치되지 않았습니다."),
    "IO_FAILURE": (ErrorCategory.INTERNAL, "문서 작업 중 파일 시스템 오류가 발생했습니다."),
    "SOURCE_BUSY": (ErrorCategory.TRANSIENT_SOURCE, "문서를 읽는 동안 원본이 변경되었습니다."),
    "DOCUMENT_TOO_LARGE": (ErrorCategory.INVALID_INPUT, "문서가 현재 텍스트 처리 상한을 넘습니다."),
    "TEXT_FORMAT_UNSUPPORTED": (
        ErrorCategory.UNSUPPORTED_FORMAT,
        "현재 장문 계획에서 지원하지 않는 텍스트 형식입니다.",
    ),
    "CHUNK_BOUNDARY": (
        ErrorCategory.INVALID_INPUT,
        "컨텍스트 제한 안에서 청크 경계를 만들 수 없습니다.",
    ),
    "CHUNK_COVERAGE_FAILED": (
        ErrorCategory.CONSISTENCY,
        "청크가 문서 전체를 정확히 한 번 포함하지 못했습니다.",
    ),
    "EVIDENCE_COVERAGE_FAILED": (
        ErrorCategory.CONSISTENCY,
        "원본 구조 요소가 Evidence에 완전하게 배정되지 않았습니다.",
    ),
    "CLAIM_LEDGER_INVALID": (
        ErrorCategory.CONSISTENCY,
        "Claim Ledger의 Evidence 참조 또는 관계가 올바르지 않습니다.",
    ),
    "COVERAGE_MATRIX_INCOMPLETE": (
        ErrorCategory.CONSISTENCY,
        "필수 Claim 또는 Evidence가 Task에 완전하게 배정되지 않았습니다.",
    ),
    "TASK_PLAN_INVALID": (
        ErrorCategory.CONSISTENCY,
        "문서 Task 계획 또는 의존관계가 올바르지 않습니다.",
    ),
    "TASK_OUTPUT_INVALID": (
        ErrorCategory.MODEL_OUTPUT,
        "문서 Task 출력이 필수 Claim·Evidence 계약을 충족하지 못했습니다.",
    ),
    "DOCUMENT_ASSEMBLY_FAILED": (
        ErrorCategory.CONSISTENCY,
        "생성된 Task 출력으로 최종 문서를 조립할 수 없습니다.",
    ),
    "FINAL_ARTIFACT_INVALID": (
        ErrorCategory.CONSISTENCY,
        "최종 문서 또는 체크포인트가 없거나 저장된 내용과 일치하지 않습니다.",
    ),
    "JOB_DEFINITION_INVALID": (
        ErrorCategory.CONSISTENCY,
        "저장된 작업 정의 또는 실행 설정을 검증할 수 없습니다.",
    ),
    "JOB_NOT_RUNNABLE": (
        ErrorCategory.INVALID_INPUT,
        "현재 상태에서는 작업을 시작하거나 재개할 수 없습니다.",
    ),
    "JOB_ALREADY_RUNNING": (
        ErrorCategory.CONSISTENCY,
        "동일한 작업 실행 프로세스가 이미 동작 중입니다.",
    ),
    "JOB_LAUNCH_FAILED": (
        ErrorCategory.INTERNAL,
        "작업 실행 프로세스를 시작하지 못했습니다.",
    ),
    "JOB_CANCELLED": (
        ErrorCategory.CANCELLED,
        "문서 작업이 안전하게 취소되었습니다.",
    ),
    "RUNNER_CANCELLATION_FAILED": (
        ErrorCategory.INTERNAL,
        "작업 실행 프로세스에 취소 신호를 전달하지 못했습니다.",
    ),
    "RUNNER_PROCESS_MISMATCH": (
        ErrorCategory.SECURITY_BLOCK,
        "저장된 작업 프로세스와 운영체제 프로세스 그룹이 일치하지 않습니다.",
    ),
    "JOB_RESULT_INVALID": (
        ErrorCategory.DATA_CORRUPTION,
        "게시 결과나 품질 보고서를 검증할 수 없습니다.",
    ),
    "NOTIFICATION_RECEIPT_INVALID": (
        ErrorCategory.DATA_CORRUPTION,
        "완료 알림 영수증을 검증할 수 없습니다.",
    ),
    "NOTIFICATION_UNAVAILABLE": (
        ErrorCategory.INTERNAL,
        "현재 환경에서 시스템 완료 알림을 사용할 수 없습니다.",
    ),
    "NOTIFICATION_FAILED": (
        ErrorCategory.INTERNAL,
        "시스템 완료 알림을 전달하지 못했습니다.",
    ),
    "RUNNER_LEASE_INVALID": (
        ErrorCategory.DATA_CORRUPTION,
        "저장된 작업 실행 상태를 검증할 수 없습니다.",
    ),
    "RUNNER_LEASE_CONFLICT": (
        ErrorCategory.CONSISTENCY,
        "작업 실행 프로세스의 소유권 상태가 일치하지 않습니다.",
    ),
    "TOKEN_BUDGET_EXCEEDED": (
        ErrorCategory.INVALID_INPUT,
        "모델 요청이 승인된 컨텍스트 예산을 초과합니다.",
    ),
    "DUPLICATE_PLAN_ITEM": (
        ErrorCategory.CONSISTENCY,
        "컨텍스트 계획에 같은 항목이 중복 포함되었습니다.",
    ),
    "NO_TEXT_DOCUMENTS": (
        ErrorCategory.INVALID_INPUT,
        "통합할 수 있는 UTF-8 텍스트 문서가 없습니다.",
    ),
    "OUTPUT_ALREADY_EXISTS": (
        ErrorCategory.INVALID_INPUT,
        "생성 문서 경로가 실행 복사본에 이미 존재합니다.",
    ),
    "MODEL_GENERATION_FAILED": (
        ErrorCategory.MODEL_OUTPUT,
        "로컬 모델이 통합 문서를 생성하지 못했습니다.",
    ),
    "MODEL_NOT_CACHED": (
        ErrorCategory.INVALID_INPUT,
        "오프라인 모드에서 선택한 모델 revision을 로컬 캐시에서 찾을 수 없습니다.",
    ),
    "MODEL_SELECTION_INVALID": (
        ErrorCategory.INVALID_INPUT,
        "선택한 Hugging Face 모델 또는 commit revision을 확인할 수 없습니다.",
    ),
    "MODEL_INCOMPATIBLE": (
        ErrorCategory.INVALID_INPUT,
        "선택한 모델은 현재 MLX 런타임 또는 장비 메모리 기준과 호환되지 않습니다.",
    ),
    "MODEL_ACCESS_DENIED": (
        ErrorCategory.INVALID_INPUT,
        "선택한 Hugging Face 모델에 접근할 권한이 없습니다.",
    ),
    "MODEL_DOWNLOAD_CONFLICT": (
        ErrorCategory.CONSISTENCY,
        "다른 모델 다운로드가 이미 진행 중입니다.",
    ),
    "MODEL_DOWNLOAD_DISK_SPACE": (
        ErrorCategory.RESOURCE_PRESSURE,
        "모델을 안전하게 다운로드할 디스크 여유 공간이 부족합니다.",
    ),
    "MODEL_DOWNLOAD_CANCELLED": (
        ErrorCategory.CANCELLED,
        "모델 다운로드가 안전하게 취소되었습니다.",
    ),
    "MODEL_DOWNLOAD_FAILED": (
        ErrorCategory.TRANSIENT_NETWORK,
        "Hugging Face 모델 다운로드를 완료하지 못했습니다.",
    ),
    "MODEL_SNAPSHOT_INVALID": (
        ErrorCategory.DATA_CORRUPTION,
        "다운로드된 모델 snapshot을 검증할 수 없습니다.",
    ),
    "MODEL_OUTPUT_EMPTY": (
        ErrorCategory.MODEL_OUTPUT,
        "로컬 모델이 비어 있는 결과를 반환했습니다.",
    ),
    "MODEL_OUTPUT_INCOMPLETE": (
        ErrorCategory.MODEL_OUTPUT,
        "로컬 모델의 출력이 잘렸거나 필수 구조를 충족하지 못했습니다.",
    ),
    "PLATFORM_UNSUPPORTED": (
        ErrorCategory.INVALID_INPUT,
        "MLX 로컬 모델은 Apple Silicon macOS에서만 실행할 수 있습니다.",
    ),
}


def revision_error(
    code: str,
    context: Mapping[str, JsonScalar] | None = None,
) -> ApplicationError:
    category, safe_message = _REVISION_ERROR_SPECS[code]
    return ApplicationError(code, category, False, safe_message, context)
