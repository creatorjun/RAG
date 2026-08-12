from __future__ import annotations

import unittest
from unittest.mock import patch

import main


class MainEntrypointTest(unittest.TestCase):
    def test_launches_gui_with_repository_root_by_default(self) -> None:
        with patch("enterprise_rag.bootstrap.gui_main", return_value=17) as gui_main:
            self.assertEqual(main.main(["--environment", "test"]), 17)
        gui_main.assert_called_once_with(
            [
                "--project-root",
                str(main.PROJECT_ROOT),
                "--environment",
                "test",
            ]
        )

    def test_preserves_explicit_project_root(self) -> None:
        with patch("enterprise_rag.bootstrap.gui_main", return_value=0) as gui_main:
            self.assertEqual(main.main(["--project-root", "/tmp/rag"]), 0)
        gui_main.assert_called_once_with(["--project-root", "/tmp/rag"])


if __name__ == "__main__":
    unittest.main()
