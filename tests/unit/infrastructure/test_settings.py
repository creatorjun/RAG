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
            "text_max_file_bytes": 1024,
            "reject_symlinks": True,
            "allowed_roots": ["data/before"],
        },
        "chunking": {
            "tokenizer_id": "conservative-utf8-bytes-v1",
            "version": "1",
            "target_tokens": 800,
            "max_tokens": 1200,
            "minimum_tokens": 80,
            "overlap_ratio": 0.12,
        },
        "models": {
            "llm": {
                "backend": "mlx-lm",
                "model_id": "mlx-community/Qwen3.6-27B-4bit",
                "revision": "c000ac2c2057d94be3fa931000c31723aac53282",
                "context_tokens": 16384,
                "reserved_tokens": 512,
            }
        },
        "synthesis": {
            "input_budget_ratio": 0.8,
            "map_prompt_overhead_tokens": 1024,
            "map_max_output_tokens": 4096,
            "reduce_prompt_overhead_tokens": 1024,
            "reduce_max_output_tokens": 4096,
            "final_max_output_tokens": 8192,
            "batch_item_overhead_tokens": 128,
            "batch_separator_tokens": 8,
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

    def test_rejects_context_budget_that_cannot_reduce(self) -> None:
        value = _valid_settings()
        models = dict(value["models"])
        models["llm"] = {
            "backend": "mlx-lm",
            "model_id": "mlx-community/Qwen3.6-27B-4bit",
            "revision": "c000ac2c2057d94be3fa931000c31723aac53282",
            "context_tokens": 4096,
            "reserved_tokens": 512,
        }
        value["models"] = models
        with self.assertRaises(ValidationError):
            Settings.model_validate(value)

    def test_rejects_final_synthesis_budget_above_context(self) -> None:
        value = _valid_settings()
        synthesis = dict(value["synthesis"])
        synthesis["final_max_output_tokens"] = 12000
        value["synthesis"] = synthesis
        with self.assertRaises(ValidationError):
            Settings.model_validate(value)

    def test_rejects_text_limit_above_global_source_limit(self) -> None:
        value = _valid_settings()
        sources = dict(value["sources"])
        sources["text_max_file_bytes"] = 2048
        value["sources"] = sources
        with self.assertRaises(ValidationError):
            Settings.model_validate(value)

    def test_rejects_worker_stale_window_at_or_above_start_timeout(self) -> None:
        value = _valid_settings()
        runtime = dict(value["runtime"])
        runtime.update(
            worker_start_timeout_seconds=15,
            worker_heartbeat_seconds=5,
            worker_missed_heartbeats=3,
        )
        value["runtime"] = runtime
        with self.assertRaises(ValidationError):
            Settings.model_validate(value)

    def test_rejects_model_download_reserve_below_one_gibibyte(self) -> None:
        value = _valid_settings()
        runtime = dict(value["runtime"])
        runtime["model_download_reserve_bytes"] = 1024**3 - 1
        value["runtime"] = runtime
        with self.assertRaises(ValidationError):
            Settings.model_validate(value)


if __name__ == "__main__":
    unittest.main()
