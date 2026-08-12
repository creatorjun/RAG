from __future__ import annotations

import unittest

from enterprise_rag.domain.errors import ApplicationError, ErrorCategory, revision_error
from enterprise_rag.presentation.gui.app import _error_notice, _job_form_error


class JobFormValidationTest(unittest.TestCase):
    def test_accepts_valid_job_form(self) -> None:
        self.assertIsNone(
            _job_form_error(
                "중복을 통합하고 운영 절차를 보존해 문서를 작성",
                "guides/integrated-guide.md",
            )
        )

    def test_identifies_missing_instruction(self) -> None:
        error = _job_form_error("   ", "integrated-guide.md")

        self.assertIsNotNone(error)
        assert error is not None
        self.assertEqual(error[2], "instruction")
        self.assertIn("작업 지시", error[0])

    def test_identifies_oversized_instruction(self) -> None:
        error = _job_form_error("가" * 20_001, "integrated-guide.md")

        self.assertIsNotNone(error)
        assert error is not None
        self.assertEqual(error[2], "instruction")
        self.assertIn("너무 깁니다", error[0])

    def test_identifies_invalid_output_path(self) -> None:
        for output_path in ("", "/tmp/guide.md", "../guide.md", "guide.txt"):
            with self.subTest(output_path=output_path):
                error = _job_form_error("문서 작성", output_path)
                self.assertIsNotNone(error)
                assert error is not None
                self.assertEqual(error[2], "output")


class ErrorNoticeTest(unittest.TestCase):
    def test_application_error_includes_actionable_guidance(self) -> None:
        message, guidance, code = _error_notice(revision_error("MODEL_NOT_CACHED"))

        self.assertIn("로컬", message)
        self.assertIn("설정 탭", guidance)
        self.assertIn("과거 Job", guidance)
        self.assertEqual(code, "MODEL_NOT_CACHED")

    def test_unexpected_error_does_not_expose_internal_detail(self) -> None:
        message, guidance, code = _error_notice(RuntimeError("secret detail"))

        self.assertNotIn("secret detail", message)
        self.assertTrue(guidance)
        self.assertEqual(code, "UNEXPECTED_ERROR")

    def test_unknown_application_code_uses_category_specific_guidance(self) -> None:
        error = ApplicationError(
            "CUSTOM_CONSISTENCY_ERROR",
            ErrorCategory.CONSISTENCY,
            False,
            "상태가 일치하지 않습니다.",
        )

        _, guidance, code = _error_notice(error)

        self.assertIn("상태를 새로고침", guidance)
        self.assertNotIn("입력과 설정을 확인", guidance)
        self.assertEqual(code, "CUSTOM_CONSISTENCY_ERROR")

    def test_running_job_error_has_specific_recovery_guidance(self) -> None:
        _, guidance, code = _error_notice(revision_error("JOB_ALREADY_RUNNING"))

        self.assertIn("이미 실행 중인 Worker", guidance)
        self.assertEqual(code, "JOB_ALREADY_RUNNING")

    def test_token_budget_error_explains_recovery_options(self) -> None:
        _, guidance, code = _error_notice(revision_error("TOKEN_BUDGET_EXCEEDED"))

        self.assertIn("실패 지점부터 복구", guidance)
        self.assertIn("context", guidance)
        self.assertEqual(code, "TOKEN_BUDGET_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
