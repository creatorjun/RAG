# tests/unit/domain/test_value_objects.py
import unittest

from enterprise_rag.domain.value_objects import RunId, Sha256Digest


class ValueObjectTest(unittest.TestCase):
    def test_accepts_safe_run_id(self) -> None:
        self.assertEqual(str(RunId("20260810t120000z-oracle")), "20260810t120000z-oracle")

    def test_rejects_unsafe_run_ids(self) -> None:
        for value in ("ab", "../escape", "UPPERCASE", "ends-", "contains space"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                RunId(value)

    def test_validates_sha256_digest(self) -> None:
        value = "a" * 64
        self.assertEqual(str(Sha256Digest(value)), value)
        with self.assertRaises(ValueError):
            Sha256Digest("not-a-digest")


if __name__ == "__main__":
    unittest.main()
