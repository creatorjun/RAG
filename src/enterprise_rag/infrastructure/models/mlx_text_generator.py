from __future__ import annotations

import asyncio
import importlib
import platform
import re
import threading
from typing import Any

from enterprise_rag.domain.errors import ApplicationError, revision_error


class MlxTextGenerator:
    def __init__(
        self,
        model_id: str,
        model_revision: str,
        maximum_context_tokens: int,
        reserved_tokens: int,
        offline_mode: bool = False,
    ) -> None:
        self._model_id = model_id
        self._model_revision = model_revision
        self._maximum_context_tokens = maximum_context_tokens
        self._reserved_tokens = reserved_tokens
        self._offline_mode = offline_mode
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
            await asyncio.to_thread(self._load)
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
            return await asyncio.to_thread(
                self._generate_sync,
                system_prompt,
                user_prompt,
                max_output_tokens,
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
        result = mlx_lm.generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=max_output_tokens,
            sampler=sample_utils.make_sampler(temp=0.0),
            verbose=False,
        )
        return self._strip_reasoning(result)

    def _load(self) -> tuple[Any, Any]:
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
                    local_path = huggingface_hub.snapshot_download(
                        repo_id=self._model_id,
                        revision=self._model_revision,
                        local_files_only=True,
                    )
                except ModuleNotFoundError as error:
                    raise revision_error(
                        "DEPENDENCY_MISSING", {"dependency": "huggingface-hub"}
                    ) from error
                except Exception as error:
                    raise revision_error("MODEL_NOT_CACHED") from error
                self._model, self._tokenizer = mlx_lm.load(str(local_path))
            else:
                self._model, self._tokenizer = mlx_lm.load(
                    self._model_id,
                    revision=self._model_revision,
                )
        return self._model, self._tokenizer

    @staticmethod
    def _strip_reasoning(value: str) -> str:
        result = re.sub(r"^\s*<think>.*?</think>\s*", "", value, flags=re.DOTALL)
        return result.strip()
