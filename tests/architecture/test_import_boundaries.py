# tests/architecture/test_import_boundaries.py
from __future__ import annotations

import ast
import unittest
from pathlib import Path

_LAYER_RANK = {
    "domain": 0,
    "application": 1,
    "infrastructure": 2,
    "presentation": 3,
}


class ImportBoundaryTest(unittest.TestCase):
    def test_dependencies_point_inward(self) -> None:
        package_root = Path(__file__).parents[2] / "src" / "enterprise_rag"
        violations: list[str] = []
        for layer, rank in _LAYER_RANK.items():
            for path in (package_root / layer).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    modules = self._modules(node)
                    for module in modules:
                        parts = module.split(".")
                        if len(parts) < 2 or parts[0] != "enterprise_rag":
                            continue
                        target = parts[1]
                        target_rank = _LAYER_RANK.get(target)
                        if target_rank is not None and target_rank > rank:
                            relative = path.relative_to(package_root).as_posix()
                            violations.append(f"{relative} imports {module}")
        self.assertEqual(violations, [])

    @staticmethod
    def _modules(node: ast.AST) -> tuple[str, ...]:
        if isinstance(node, ast.Import):
            return tuple(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            return (node.module,)
        return ()


if __name__ == "__main__":
    unittest.main()
