from __future__ import annotations

import unittest

from enterprise_rag.application.use_cases.polish_document import PolishDocument


class ProgressiveDocumentQualityTest(unittest.TestCase):
    def test_publication_cleanup_removes_internal_markers_duplicates_and_secrets(self) -> None:
        paragraph = (
            "운영자는 서비스 상태와 로그를 함께 확인한 뒤 다음 단계로 진행해야 합니다. "
            "이 문장은 중복 검토를 시험하기에 충분히 깁니다. [source:guide.md]"
        )
        draft = (
            "# 문서\n\n"
            f"{paragraph}\n\n"
            f"{paragraph}\n\n"
            "내부 참조 [claim:C000001] [evidence:E000001]\n\n"
            "`DEMO_ACCESS_TOKEN=demo-token-value`로 실행한다."
        )

        polished = PolishDocument().execute(draft)

        self.assertEqual(polished.count("운영자는 서비스 상태와 로그를"), 1)
        self.assertNotIn("[claim:", polished)
        self.assertNotIn("[evidence:", polished)
        self.assertNotIn("demo-token-value", polished)
        self.assertIn("DEMO_ACCESS_TOKEN=[민감정보 제거]", polished)


if __name__ == "__main__":
    unittest.main()
