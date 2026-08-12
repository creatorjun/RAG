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
