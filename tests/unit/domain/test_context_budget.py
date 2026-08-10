# tests/unit/domain/test_context_budget.py
import unittest

from enterprise_rag.domain.context_budget import TokenBudget
from enterprise_rag.domain.errors import ApplicationError


class TokenBudgetTest(unittest.TestCase):
    def test_calculates_hard_context_capacity(self) -> None:
        budget = TokenBudget(16384, 1024, 3072, 512, 0.8)
        self.assertEqual(budget.content_capacity_tokens, 11776)
        self.assertEqual(budget.total_tokens(11776), 16384)
        budget.ensure_fits(11776)

    def test_rejects_content_over_capacity(self) -> None:
        budget = TokenBudget(4096, 512, 512, 256, 0.8)
        with self.assertRaises(ApplicationError) as captured:
            budget.ensure_fits(budget.content_capacity_tokens + 1)
        self.assertEqual(captured.exception.code, "TOKEN_BUDGET_EXCEEDED")

    def test_rejects_invalid_budget(self) -> None:
        with self.assertRaises(ValueError):
            TokenBudget(1024, 512, 512, 128, 0.8)
        with self.assertRaises(ValueError):
            TokenBudget(4096, 512, 512, 128, 0.0)


if __name__ == "__main__":
    unittest.main()
