# tests/architecture/test_import_boundaries.py
from __future__ import annotations

import ast
import unittest
from pathlib import Path

_ALLOWED_TARGETS = {
    "domain": frozenset({"domain"}),
    "application": frozenset({"domain", "application"}),
    "infrastructure": frozenset({"domain", "application", "infrastructure"}),
    "presentation": frozenset({"domain", "application", "presentation"}),
}


class ImportBoundaryTest(unittest.TestCase):
    def test_dependencies_point_inward(self) -> None:
        package_root = Path(__file__).parents[2] / "src" / "enterprise_rag"
        violations: list[str] = []
        for layer, allowed_targets in _ALLOWED_TARGETS.items():
            for path in (package_root / layer).rglob("*.py"):
                if path.name == "__main__.py":
                    # Executable compatibility shims are composition roots even when
                    # physically located below presentation.
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    modules = self._modules(node)
                    for module in modules:
                        parts = module.split(".")
                        if len(parts) < 2 or parts[0] != "enterprise_rag":
                            continue
                        target = parts[1]
                        if target not in allowed_targets:
                            relative = path.relative_to(package_root).as_posix()
                            violations.append(f"{relative} imports {module}")
        self.assertEqual(violations, [])

    def test_local_job_stage_composite_does_not_select_concrete_adapters(self) -> None:
        package_root = Path(__file__).parents[2] / "src" / "enterprise_rag"
        path = package_root / "infrastructure/jobs/local_document_job_stages.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        concrete_imports = [
            module
            for node in ast.walk(tree)
            for module in self._modules(node)
            if module.startswith("enterprise_rag.infrastructure.")
        ]
        self.assertEqual(concrete_imports, [])

    @staticmethod
    def _modules(node: ast.AST) -> tuple[str, ...]:
        if isinstance(node, ast.Import):
            return tuple(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            return (node.module,)
        return ()


if __name__ == "__main__":
    unittest.main()
