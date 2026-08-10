# src/enterprise_rag/infrastructure/config/settings.py
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from enterprise_rag.domain.context_budget import TokenBudget
from enterprise_rag.domain.errors import revision_error


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PathsSettings(_StrictModel):
    before_root: Path
    after_root: Path
    var_root: Path
    database: Path
    object_store: Path
    vector_indexes: Path
    artifact_generations: Path
    staging: Path
    quarantine: Path
    logs: Path


class RuntimeSettings(_StrictModel):
    python: str = "3.12"
    max_parallel_llm_jobs: int = Field(default=1, ge=1, le=1)
    parse_concurrency: int = Field(default=2, ge=1, le=16)
    network_concurrency: int = Field(default=2, ge=1, le=16)


class SourcesSettings(_StrictModel):
    max_file_bytes: int = Field(default=2 * 1024 * 1024 * 1024, ge=1)
    text_max_file_bytes: int = Field(default=128 * 1024 * 1024, ge=1)
    reject_symlinks: bool = True
    allowed_roots: tuple[Path, ...]


class ChunkingSettings(_StrictModel):
    tokenizer_id: Literal["conservative-utf8-bytes-v1"]
    version: str = Field(min_length=1)
    target_tokens: int = Field(ge=128)
    max_tokens: int = Field(ge=256)
    minimum_tokens: int = Field(ge=1)
    overlap_ratio: float = Field(ge=0, le=0.25)

    @model_validator(mode="after")
    def validate_token_limits(self) -> ChunkingSettings:
        if not self.minimum_tokens <= self.target_tokens <= self.max_tokens:
            raise ValueError("chunk token limits are inconsistent")
        return self


class LlmSettings(_StrictModel):
    context_tokens: Literal[4096, 16384, 24576, 32768]
    reserved_tokens: int = Field(ge=128)


class ModelsSettings(_StrictModel):
    llm: LlmSettings


class SynthesisSettings(_StrictModel):
    input_budget_ratio: float = Field(gt=0, le=0.8)
    map_prompt_overhead_tokens: int = Field(ge=128)
    map_max_output_tokens: int = Field(ge=256)
    reduce_prompt_overhead_tokens: int = Field(ge=128)
    reduce_max_output_tokens: int = Field(ge=256)
    batch_item_overhead_tokens: int = Field(ge=64)
    batch_separator_tokens: int = Field(ge=0)


class DocumentWorkspaceSettings(_StrictModel):
    run_id_pattern: str
    reject_symlinks: bool = True
    reject_junctions: bool = True
    never_overwrite_run: bool = True
    require_input_manifest: bool = True
    require_comparison_report: bool = True
    finalize_immutable: bool = True

    @model_validator(mode="after")
    def enforce_security_flags(self) -> DocumentWorkspaceSettings:
        flags = (
            self.reject_symlinks,
            self.reject_junctions,
            self.never_overwrite_run,
            self.require_input_manifest,
            self.require_comparison_report,
            self.finalize_immutable,
        )
        if not all(flags):
            raise ValueError("document workspace security flags must be enabled")
        return self


class WebSettings(_StrictModel):
    enabled: bool = False
    provider: Literal["disabled", "tavily"] = "disabled"
    secret_ref: str | None = None
    allowed_domains: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_provider(self) -> WebSettings:
        if not self.enabled and self.provider != "disabled":
            raise ValueError("disabled web access requires the disabled provider")
        if self.enabled and (self.provider == "disabled" or not self.secret_ref):
            raise ValueError("enabled web access requires a provider and secret reference")
        return self


class LoggingSettings(_StrictModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    format: Literal["jsonl"] = "jsonl"
    include_source_text: bool = False
    include_model_output: bool = False

    @model_validator(mode="after")
    def reject_sensitive_logging(self) -> LoggingSettings:
        if self.include_source_text or self.include_model_output:
            raise ValueError("source text and model output logging must remain disabled")
        return self


class Settings(_StrictModel):
    schema_version: Literal[1]
    environment: Literal["development", "test", "production"]
    paths: PathsSettings
    runtime: RuntimeSettings
    sources: SourcesSettings
    chunking: ChunkingSettings
    models: ModelsSettings
    synthesis: SynthesisSettings
    document_workspace: DocumentWorkspaceSettings
    web: WebSettings
    logging: LoggingSettings

    @model_validator(mode="after")
    def validate_long_document_budgets(self) -> Settings:
        if self.sources.text_max_file_bytes > self.sources.max_file_bytes:
            raise ValueError("text source limit exceeds global source limit")
        map_budget = TokenBudget(
            self.models.llm.context_tokens,
            self.synthesis.map_prompt_overhead_tokens,
            self.synthesis.map_max_output_tokens,
            self.models.llm.reserved_tokens,
            self.synthesis.input_budget_ratio,
        )
        reduce_budget = TokenBudget(
            self.models.llm.context_tokens,
            self.synthesis.reduce_prompt_overhead_tokens,
            self.synthesis.reduce_max_output_tokens,
            self.models.llm.reserved_tokens,
            self.synthesis.input_budget_ratio,
        )
        if self.chunking.max_tokens > map_budget.content_capacity_tokens:
            raise ValueError("chunk maximum exceeds map content capacity")
        minimum_reduce_capacity = (
            2
            * (self.synthesis.reduce_max_output_tokens + self.synthesis.batch_item_overhead_tokens)
            + self.synthesis.batch_separator_tokens
        )
        if reduce_budget.content_capacity_tokens < minimum_reduce_capacity:
            raise ValueError("reduce budget cannot make hierarchical progress")
        return self


@dataclass(frozen=True, slots=True)
class ResolvedPaths:
    project_root: Path
    before_root: Path
    after_root: Path
    var_root: Path
    database: Path
    object_store: Path
    vector_indexes: Path
    artifact_generations: Path
    staging: Path
    quarantine: Path
    logs: Path


@dataclass(frozen=True, slots=True)
class LoadedSettings:
    settings: Settings
    paths: ResolvedPaths


class SettingsLoader:
    def __init__(self, project_root: Path, environment: Mapping[str, str] | None = None) -> None:
        self._project_root = project_root.expanduser().resolve(strict=True)
        self._environment = dict(os.environ if environment is None else environment)

    def load(self, environment_name: str | None = None) -> LoadedSettings:
        selected = environment_name or self._environment.get("RAG_ENVIRONMENT", "development")
        if selected not in {"development", "test", "production"}:
            raise revision_error("CONFIG_INVALID", {"field": "environment"})
        config_root = self._project_root / "config"
        value = self._load_yaml(config_root / "default.yaml")
        overlay_path = config_root / f"{selected}.yaml"
        if overlay_path.is_file():
            value = self._deep_merge(value, self._load_yaml(overlay_path))
        local_path = config_root / "local.yaml"
        if local_path.is_file() and selected != "production":
            value = self._deep_merge(value, self._load_yaml(local_path))
        value = self._deep_merge(value, self._allowed_environment_overlay(selected))
        try:
            settings = Settings.model_validate(value)
        except ValidationError as error:
            field = ".".join(str(part) for part in error.errors()[0].get("loc", ()))
            raise revision_error("CONFIG_INVALID", {"field": field}) from error
        paths = self._resolve_and_validate_paths(settings)
        return LoadedSettings(settings, paths)

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        try:
            import yaml
        except ModuleNotFoundError as error:
            raise revision_error("DEPENDENCY_MISSING", {"dependency": "PyYAML"}) from error
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
            raise revision_error("CONFIG_INVALID", {"file": path.name}) from error
        if not isinstance(value, dict):
            raise revision_error("CONFIG_INVALID", {"file": path.name})
        return value

    def _allowed_environment_overlay(self, selected: str) -> dict[str, Any]:
        overlay: dict[str, Any] = {"environment": selected}
        level = self._environment.get("RAG_LOG_LEVEL")
        if level is not None:
            overlay["logging"] = {"level": level}
        return overlay

    def _resolve_and_validate_paths(self, settings: Settings) -> ResolvedPaths:
        values = {name: self._resolve(path) for name, path in settings.paths.model_dump().items()}
        paths = ResolvedPaths(project_root=self._project_root, **values)
        if self._overlaps(paths.before_root, paths.after_root):
            raise revision_error("BEFORE_AFTER_OVERLAP")
        if self._overlaps(paths.before_root, paths.var_root) or self._overlaps(
            paths.after_root, paths.var_root
        ):
            raise revision_error("CONFIG_INVALID", {"field": "paths"})
        allowed_roots = tuple(self._resolve(path) for path in settings.sources.allowed_roots)
        if allowed_roots != (paths.before_root,):
            raise revision_error("CONFIG_INVALID", {"field": "sources.allowed_roots"})
        internal_write_paths = (
            paths.database.parent,
            paths.object_store,
            paths.vector_indexes,
            paths.artifact_generations,
            paths.staging,
            paths.quarantine,
            paths.logs,
        )
        if not all(self._is_within(path, paths.var_root) for path in internal_write_paths):
            raise revision_error("CONFIG_INVALID", {"field": "paths.var_root"})
        return paths

    def _resolve(self, path: Path) -> Path:
        candidate = path if path.is_absolute() else self._project_root / path
        return candidate.resolve(strict=False)

    @staticmethod
    def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
        result = dict(base)
        for key, value in overlay.items():
            if isinstance(result.get(key), dict) and isinstance(value, dict):
                result[key] = SettingsLoader._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @classmethod
    def _overlaps(cls, left: Path, right: Path) -> bool:
        return left == right or cls._is_within(left, right) or cls._is_within(right, left)
