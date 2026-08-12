from __future__ import annotations

import asyncio
import importlib
import json
import platform
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from enterprise_rag.application.ports.cancellation import CancellationTokenPort
from enterprise_rag.domain.errors import ApplicationError, revision_error


class MlxTextGenerator:
    def __init__(
        self,
        model_id: str,
        model_revision: str,
        maximum_context_tokens: int,
        reserved_tokens: int,
        offline_mode: bool = False,
        cancellation: CancellationTokenPort | None = None,
    ) -> None:
        self._model_id = model_id
        self._model_revision = model_revision
        self._maximum_context_tokens = maximum_context_tokens
        self._reserved_tokens = reserved_tokens
        self._offline_mode = offline_mode
        self._cancellation = cancellation
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._load_lock = threading.Lock()

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def model_revision(self) -> str:
        return self._model_revision

    async def prepare(self) -> None:
        try:
            self._raise_if_cancelled()
            await asyncio.to_thread(self._load)
            self._raise_if_cancelled()
        except ApplicationError:
            raise
        except Exception as error:
            raise revision_error("MODEL_GENERATION_FAILED") from error

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        try:
            self._raise_if_cancelled()
            return await asyncio.to_thread(
                self._generate_sync,
                system_prompt,
                user_prompt,
                max_output_tokens,
                None,
            )
        except ApplicationError:
            raise
        except Exception as error:
            raise revision_error("MODEL_GENERATION_FAILED") from error

    async def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        observer: Callable[[str], None],
    ) -> str:
        try:
            self._raise_if_cancelled()
            return await asyncio.to_thread(
                self._generate_sync,
                system_prompt,
                user_prompt,
                max_output_tokens,
                observer,
            )
        except ApplicationError:
            raise
        except Exception as error:
            raise revision_error("MODEL_GENERATION_FAILED") from error

    def _generate_sync(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        observer: Callable[[str], None] | None,
    ) -> str:
        model, tokenizer = self._load()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            prompt = tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=False,
                enable_thinking=False,
            )
        except TypeError:
            prompt = tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=False,
            )
        prompt_tokens = len(tokenizer.encode(prompt))
        allowed = self._maximum_context_tokens - max_output_tokens - self._reserved_tokens
        if prompt_tokens > allowed:
            raise revision_error(
                "TOKEN_BUDGET_EXCEEDED",
                {"content_tokens": prompt_tokens, "content_capacity_tokens": allowed},
            )
        try:
            mlx_lm = importlib.import_module("mlx_lm")
            sample_utils = importlib.import_module("mlx_lm.sample_utils")
        except ModuleNotFoundError as error:
            raise revision_error("DEPENDENCY_MISSING", {"dependency": "mlx-lm"}) from error
        self._raise_if_cancelled()
        responses = mlx_lm.stream_generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=max_output_tokens,
            sampler=sample_utils.make_sampler(temp=0.0),
        )
        pieces: list[str] = []
        try:
            for response in responses:
                self._raise_if_cancelled()
                piece = str(response.text)
                pieces.append(piece)
                if observer is not None:
                    observer(piece)
        finally:
            close = getattr(responses, "close", None)
            if close is not None:
                close()
        self._raise_if_cancelled()
        result = "".join(pieces)
        return self._strip_reasoning(result)

    def _load(self) -> tuple[Any, Any]:
        self._raise_if_cancelled()
        if self._model is not None and self._tokenizer is not None:
            return self._model, self._tokenizer
        with self._load_lock:
            if self._model is not None and self._tokenizer is not None:
                return self._model, self._tokenizer
            if platform.system() != "Darwin" or platform.machine() != "arm64":
                raise revision_error("PLATFORM_UNSUPPORTED")
            try:
                mlx_lm = importlib.import_module("mlx_lm")
            except ModuleNotFoundError as error:
                raise revision_error("DEPENDENCY_MISSING", {"dependency": "mlx-lm"}) from error
            if self._offline_mode:
                try:
                    huggingface_hub = importlib.import_module("huggingface_hub")
                except ModuleNotFoundError as error:
                    raise revision_error(
                        "DEPENDENCY_MISSING", {"dependency": "huggingface-hub"}
                    ) from error
                local_path = self._resolve_offline_snapshot(huggingface_hub)
                self._model, self._tokenizer = mlx_lm.load(str(local_path))
            else:
                self._model, self._tokenizer = mlx_lm.load(
                    self._model_id,
                    revision=self._model_revision,
                )
        self._raise_if_cancelled()
        return self._model, self._tokenizer

    def _resolve_offline_snapshot(self, module: Any) -> Path:
        try:
            downloaded = module.snapshot_download(
                repo_id=self._model_id,
                revision=self._model_revision,
                local_files_only=True,
            )
            snapshot = Path(downloaded).expanduser().resolve(strict=True)
            self._validate_runtime_snapshot(snapshot)
            return snapshot
        except Exception:
            # huggingface-hub 1.27+ rejects an otherwise runnable local snapshot
            # when repository-only files such as README.md are absent. The model
            # catalog and downloader intentionally validate MLX runtime files.
            scanned_snapshot = self._find_scanned_snapshot(module)
            if scanned_snapshot is None:
                raise revision_error(
                    "MODEL_NOT_CACHED",
                    {
                        "model_id": self._model_id,
                        "model_revision": self._model_revision,
                    },
                ) from None
            try:
                self._validate_runtime_snapshot(scanned_snapshot)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                raise revision_error(
                    "MODEL_SNAPSHOT_INVALID",
                    {
                        "model_id": self._model_id,
                        "model_revision": self._model_revision,
                    },
                ) from None
            return scanned_snapshot

    def _find_scanned_snapshot(self, module: Any) -> Path | None:
        try:
            cache = module.scan_cache_dir()
            for repository in cache.repos:
                if (
                    getattr(repository, "repo_type", None) != "model"
                    or getattr(repository, "repo_id", None) != self._model_id
                ):
                    continue
                for revision in repository.revisions:
                    if (
                        str(getattr(revision, "commit_hash", "")).lower()
                        == self._model_revision
                    ):
                        return Path(revision.snapshot_path).expanduser().resolve(
                            strict=False
                        )
        except Exception:
            return None
        return None

    def _validate_runtime_snapshot(self, snapshot: Path) -> None:
        if not snapshot.is_dir() or snapshot.name != self._model_revision:
            raise ValueError("snapshot identity is invalid")
        config = json.loads((snapshot / "config.json").read_text(encoding="utf-8"))
        if not isinstance(config, dict) or not config:
            raise ValueError("model config is invalid")
        weights = tuple(snapshot.rglob("*.safetensors")) + tuple(
            snapshot.rglob("*.npz")
        )
        if not weights or any(not path.is_file() for path in weights):
            raise ValueError("model weights are missing")

    def _raise_if_cancelled(self) -> None:
        if self._cancellation is not None:
            self._cancellation.raise_if_cancelled()

    @staticmethod
    def _strip_reasoning(value: str) -> str:
        result = re.sub(r"^\s*<think>.*?</think>\s*", "", value, flags=re.DOTALL)
        return result.strip()
