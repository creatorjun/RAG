from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.infrastructure.models.mlx_text_generator import MlxTextGenerator


class _FakeTokenizer:
    def __init__(self, token_count: int = 3, reject_thinking_option: bool = False) -> None:
        self.token_count = token_count
        self.reject_thinking_option = reject_thinking_option
        self.template_calls = 0

    def apply_chat_template(self, messages: object, **kwargs: object) -> str:
        self.template_calls += 1
        if self.reject_thinking_option and "enable_thinking" in kwargs:
            raise TypeError("unsupported option")
        return "formatted prompt"

    def encode(self, prompt: str) -> list[int]:
        return [1] * self.token_count


def _generator(context_tokens: int = 1024) -> MlxTextGenerator:
    return MlxTextGenerator("test/model", "a" * 40, context_tokens, 128)


class MlxTextGeneratorTest(unittest.TestCase):
    def test_loads_pinned_revision_once_and_exposes_identity(self) -> None:
        generator = _generator()
        tokenizer = _FakeTokenizer()
        load = Mock(return_value=(object(), tokenizer))
        module = SimpleNamespace(load=load)
        with (
            patch("platform.system", return_value="Darwin"),
            patch("platform.machine", return_value="arm64"),
            patch("importlib.import_module", return_value=module),
        ):
            asyncio.run(generator.prepare())
            asyncio.run(generator.prepare())
        self.assertEqual(generator.model_id, "test/model")
        self.assertEqual(generator.model_revision, "a" * 40)
        load.assert_called_once_with("test/model", revision="a" * 40)

    def test_offline_mode_resolves_only_pinned_local_snapshot(self) -> None:
        generator = MlxTextGenerator(
            "test/model", "a" * 40, 1024, 128, offline_mode=True
        )
        tokenizer = _FakeTokenizer()
        load = Mock(return_value=(object(), tokenizer))
        snapshot_download = Mock(return_value="/cache/pinned-model")
        modules = {
            "mlx_lm": SimpleNamespace(load=load),
            "huggingface_hub": SimpleNamespace(snapshot_download=snapshot_download),
        }
        with (
            patch("platform.system", return_value="Darwin"),
            patch("platform.machine", return_value="arm64"),
            patch("importlib.import_module", side_effect=lambda name: modules[name]),
        ):
            asyncio.run(generator.prepare())
        snapshot_download.assert_called_once_with(
            repo_id="test/model",
            revision="a" * 40,
            local_files_only=True,
        )
        load.assert_called_once_with("/cache/pinned-model")

    def test_generates_deterministically_and_strips_reasoning(self) -> None:
        generator = _generator()
        tokenizer = _FakeTokenizer(reject_thinking_option=True)
        generator._model = object()
        generator._tokenizer = tokenizer
        generate = Mock(return_value="<think>private reasoning</think>\n# result")
        sampler = object()
        modules = {
            "mlx_lm": SimpleNamespace(generate=generate),
            "mlx_lm.sample_utils": SimpleNamespace(make_sampler=Mock(return_value=sampler)),
        }
        with patch("importlib.import_module", side_effect=lambda name: modules[name]):
            result = asyncio.run(generator.generate("system", "user", 128))
        self.assertEqual(result, "# result")
        self.assertEqual(tokenizer.template_calls, 2)
        generate.assert_called_once()
        self.assertIs(generate.call_args.kwargs["sampler"], sampler)

    def test_rejects_prompt_over_context_budget(self) -> None:
        generator = _generator(context_tokens=512)
        generator._model = object()
        generator._tokenizer = _FakeTokenizer(token_count=300)
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(generator.generate("system", "user", 128))
        self.assertEqual(captured.exception.code, "TOKEN_BUDGET_EXCEEDED")

    def test_reports_unsupported_platform_and_missing_dependency(self) -> None:
        with patch("platform.system", return_value="Linux"):
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(_generator().prepare())
        self.assertEqual(captured.exception.code, "PLATFORM_UNSUPPORTED")

        with (
            patch("platform.system", return_value="Darwin"),
            patch("platform.machine", return_value="arm64"),
            patch("importlib.import_module", side_effect=ModuleNotFoundError),
        ):
            with self.assertRaises(ApplicationError) as captured:
                asyncio.run(_generator().prepare())
        self.assertEqual(captured.exception.code, "DEPENDENCY_MISSING")

    def test_maps_unexpected_runtime_failure_to_safe_error(self) -> None:
        generator = _generator()
        generator._model = object()
        tokenizer = _FakeTokenizer()
        tokenizer.apply_chat_template = Mock(side_effect=RuntimeError("secret runtime detail"))
        generator._tokenizer = tokenizer
        with self.assertRaises(ApplicationError) as captured:
            asyncio.run(generator.generate("system", "user", 128))
        self.assertEqual(captured.exception.code, "MODEL_GENERATION_FAILED")
        self.assertNotIn("secret runtime detail", captured.exception.safe_message)


if __name__ == "__main__":
    unittest.main()
