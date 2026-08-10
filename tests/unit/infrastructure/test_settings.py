# tests/unit/infrastructure/test_settings.py
from __future__ import annotations

import unittest

from pydantic import ValidationError

from enterprise_rag.infrastructure.config.settings import Settings


def _valid_settings() -> dict[str, object]:
    return {
        "schema_version": 1,
        "environment": "test",
        "paths": {
            "before_root": "data/before",
            "after_root": "data/after",
            "var_root": "var",
            "database": "var/database/metadata.sqlite3",
            "object_store": "var/objects",
            "vector_indexes": "var/indexes/vectors",
            "artifact_generations": "var/artifacts/generations",
            "staging": "var/staging",
            "quarantine": "var/quarantine",
            "logs": "var/logs",
        },
        "runtime": {
            "python": "3.12",
            "max_parallel_llm_jobs": 1,
            "parse_concurrency": 2,
            "network_concurrency": 2,
        },
        "sources": {
            "max_file_bytes": 1024,
            "reject_symlinks": True,
            "allowed_roots": ["data/before"],
        },
        "document_workspace": {
            "run_id_pattern": "^[a-z0-9][a-z0-9._-]{1,62}[a-z0-9]$",
            "reject_symlinks": True,
            "reject_junctions": True,
            "never_overwrite_run": True,
            "require_input_manifest": True,
            "require_comparison_report": True,
            "finalize_immutable": True,
        },
        "web": {
            "enabled": False,
            "provider": "disabled",
            "secret_ref": None,
            "allowed_domains": [],
        },
        "logging": {
            "level": "INFO",
            "format": "jsonl",
            "include_source_text": False,
            "include_model_output": False,
        },
    }


class SettingsTest(unittest.TestCase):
    def test_accepts_secure_baseline(self) -> None:
        settings = Settings.model_validate(_valid_settings())
        self.assertEqual(settings.environment, "test")
        self.assertFalse(settings.web.enabled)

    def test_rejects_unknown_fields(self) -> None:
        value = _valid_settings()
        value["unknown"] = True
        with self.assertRaises(ValidationError):
            Settings.model_validate(value)

    def test_rejects_disabled_workspace_guard(self) -> None:
        value = _valid_settings()
        workspace = dict(value["document_workspace"])
        workspace["finalize_immutable"] = False
        value["document_workspace"] = workspace
        with self.assertRaises(ValidationError):
            Settings.model_validate(value)

    def test_rejects_sensitive_logging(self) -> None:
        value = _valid_settings()
        logging = dict(value["logging"])
        logging["include_source_text"] = True
        value["logging"] = logging
        with self.assertRaises(ValidationError):
            Settings.model_validate(value)


if __name__ == "__main__":
    unittest.main()
