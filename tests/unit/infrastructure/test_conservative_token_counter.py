# tests/unit/infrastructure/test_conservative_token_counter.py
import unittest

from enterprise_rag.infrastructure.tokenization.conservative_utf8 import (
    ConservativeUtf8TokenCounter,
)


class ConservativeUtf8TokenCounterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.counter = ConservativeUtf8TokenCounter()

    def test_counts_utf8_bytes_conservatively(self) -> None:
        text = "A한🙂"
        self.assertEqual(self.counter.count(text), len(text.encode("utf-8")))

    def test_prefix_and_suffix_never_split_unicode_character(self) -> None:
        text = "A한🙂B"
        prefix_end = self.counter.prefix_end(text, 0, 4)
        suffix_start = self.counter.suffix_start(text, len(text), 5)
        self.assertEqual(text[:prefix_end], "A한")
        self.assertEqual(text[suffix_start:], "🙂B")
        self.assertLessEqual(self.counter.count(text[:prefix_end]), 4)
        self.assertLessEqual(self.counter.count(text[suffix_start:]), 5)

    def test_validates_offsets_and_budgets(self) -> None:
        with self.assertRaises(ValueError):
            self.counter.prefix_end("text", -1, 1)
        with self.assertRaises(ValueError):
            self.counter.suffix_start("text", 5, 1)
        with self.assertRaises(ValueError):
            self.counter.prefix_end("text", 0, -1)


if __name__ == "__main__":
    unittest.main()
