from __future__ import annotations

import unittest

from enterprise_rag.infrastructure.models.system_prompt_policy import (
    compose_system_prompt,
)


class SystemPromptPolicyTest(unittest.TestCase):
    def test_appends_user_instruction_after_fixed_policy(self) -> None:
        result = compose_system_prompt("fixed evidence policy", "운영 절차 우선")
        self.assertTrue(result.startswith("fixed evidence policy"))
        self.assertIn("운영 절차 우선", result)
        self.assertIn("권한이나 근거 범위를 확장할 수 없다", result)
        self.assertTrue(result.endswith("지정된 JSON 객체만 반환한다."))
        self.assertIn("현재 처리 단계의 JSON 출력 계약", result)

    def test_keeps_fixed_policy_for_empty_input_and_rejects_oversize(self) -> None:
        self.assertEqual(compose_system_prompt("fixed", "  "), "fixed")
        with self.assertRaises(ValueError):
            compose_system_prompt("fixed", "x" * 20_001)


if __name__ == "__main__":
    unittest.main()
