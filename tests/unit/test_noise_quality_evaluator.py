from __future__ import annotations

import unittest
from pathlib import Path

import yaml
from scripts.evaluate_noise_quality import DEFAULT_ORACLE, evaluate


class NoiseQualityEvaluatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        loaded = yaml.safe_load(DEFAULT_ORACLE.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict)
        cls.oracle = loaded
        cls.source_root = Path("data/before/oracle-linux-9.8")

    def test_oracle_terms_exist_in_the_source_fixture(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(self.source_root.glob("*.md"))
        )
        groups = (
            "required_current_facts",
            "rejected_claims_not_to_present_as_current",
            "superseded_claims_not_to_present_as_current",
        )
        for group in groups:
            records = self.oracle[group]
            assert isinstance(records, list)
            for record in records:
                terms = record.get("required_terms", record.get("literals", []))
                for term in terms:
                    with self.subTest(group=group, term=term):
                        self.assertIn(term, source)
        for group in (
            "nontechnical_forbidden_literals",
            "secret_literals_forbidden",
        ):
            for literal in self.oracle[group]:
                with self.subTest(group=group, literal=literal):
                    self.assertIn(literal, source)

    def test_dataset_manifest_lists_every_dataset_document(self) -> None:
        loaded = yaml.safe_load(
            (self.source_root / "dataset.yaml").read_text(encoding="utf-8")
        )
        assert isinstance(loaded, dict)

        expected = {
            path.name
            for path in self.source_root.glob("*.md")
        }

        self.assertEqual(set(loaded["documents"]), expected)

    def test_accepts_current_technical_facts_without_noise(self) -> None:
        document = """
# Example API 운영

현재 서비스 포트는 `8443/tcp`다. `example-api.service`에는
`LimitNOFILE=65536`과 `TimeoutStopSec=45s`를 적용한다.

```bash
sudo systemctl daemon-reload
```
"""

        result = evaluate(document, self.oracle)

        self.assertTrue(result["passed"])
        self.assertEqual(result["metrics"]["current_fact_recall"], 1.0)

    def test_rejects_nontechnical_secret_and_unqualified_legacy_content(self) -> None:
        document = """
# 잘못된 결과

파란 수달처럼 민첩하게 움직인다. EXAMPLE_API_TOKEN은
demo-token-plain-text-DO-NOT-USE다. service network restart를 실행한다.
"""

        result = evaluate(document, self.oracle)

        self.assertFalse(result["passed"])
        self.assertEqual(result["metrics"]["nontechnical_literal_leakage"], 1)
        self.assertEqual(result["metrics"]["secret_literal_leakage"], 1)
        self.assertEqual(result["metrics"]["superseded_claims_presented_as_current"], 1)

    def test_allows_legacy_literal_when_clearly_qualified(self) -> None:
        document = """
# 현재 운영 기준

현재 서비스 포트는 `8443/tcp`다. `example-api.service`에는
`LimitNOFILE=65536`과 `TimeoutStopSec=45s`를 적용하고
`systemctl daemon-reload`를 수행한다.

## 레거시 마이그레이션 주의

Oracle Linux 7의 폐기된 `service network restart` 절차는 현재 사용하지 않는다.
"""

        result = evaluate(document, self.oracle)

        self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
