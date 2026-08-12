from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from enterprise_rag.domain.errors import ApplicationError
from enterprise_rag.infrastructure.jobs.thread_cancellation import (
    ThreadCancellationToken,
)
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
        revision = "a" * 40
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / revision
            snapshot.mkdir()
            (snapshot / "config.json").write_text(
                json.dumps({"model_type": "test"}), encoding="utf-8"
            )
            (snapshot / "model.safetensors").write_bytes(b"weights")
            generator = MlxTextGenerator(
                "test/model", revision, 1024, 128, offline_mode=True
            )
            tokenizer = _FakeTokenizer()
            load = Mock(return_value=(object(), tokenizer))
            snapshot_download = Mock(return_value=str(snapshot))
            modules = {
                "mlx_lm": SimpleNamespace(load=load),
                "huggingface_hub": SimpleNamespace(
                    snapshot_download=snapshot_download
                ),
            }
            with (
                patch("platform.system", return_value="Darwin"),
                patch("platform.machine", return_value="arm64"),
                patch(
                    "importlib.import_module", side_effect=lambda name: modules[name]
                ),
            ):
                asyncio.run(generator.prepare())
            snapshot_download.assert_called_once_with(
                repo_id="test/model",
                revision=revision,
                local_files_only=True,
            )
            load.assert_called_once_with(str(snapshot.resolve()))

    def test_offline_mode_accepts_runnable_scanned_snapshot_when_hub_manifest_is_incomplete(
        self,
    ) -> None:
        revision = "b" * 40
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary) / revision
            snapshot.mkdir()
            (snapshot / "config.json").write_text(
                json.dumps({"model_type": "test"}), encoding="utf-8"
            )
            (snapshot / "model.safetensors").write_bytes(b"weights")
            cache_revision = SimpleNamespace(
                commit_hash=revision,
                snapshot_path=snapshot,
            )
            cache_repository = SimpleNamespace(
                repo_id="test/model",
                repo_type="model",
                revisions=(cache_revision,),
            )
            hub = SimpleNamespace(
                snapshot_download=Mock(side_effect=RuntimeError("incomplete manifest")),
                scan_cache_dir=Mock(
                    return_value=SimpleNamespace(repos=(cache_repository,))
                ),
            )
            load = Mock(return_value=(object(), _FakeTokenizer()))
            modules = {
                "mlx_lm": SimpleNamespace(load=load),
                "huggingface_hub": hub,
            }
            generator = MlxTextGenerator(
                "test/model", revision, 1024, 128, offline_mode=True
            )
            with (
                patch("platform.system", return_value="Darwin"),
                patch("platform.machine", return_value="arm64"),
                patch(
                    "importlib.import_module", side_effect=lambda name: modules[name]
                ),
            ):
                asyncio.run(generator.prepare())

            load.assert_called_once_with(str(snapshot.resolve()))

    def test_offline_mode_distinguishes_missing_and_invalid_scanned_snapshot(
        self,
    ) -> None:
        revision = "c" * 40
        empty_cache = SimpleNamespace(
            snapshot_download=Mock(side_effect=RuntimeError("not found")),
            scan_cache_dir=Mock(return_value=SimpleNamespace(repos=())),
        )
        with tempfile.TemporaryDirectory() as temporary:
            invalid_snapshot = Path(temporary) / revision
            invalid_snapshot.mkdir()
            invalid_revision = SimpleNamespace(
                commit_hash=revision,
                snapshot_path=invalid_snapshot,
            )
            invalid_cache = SimpleNamespace(
                snapshot_download=Mock(side_effect=RuntimeError("incomplete")),
                scan_cache_dir=Mock(
                    return_value=SimpleNamespace(
                        repos=(
                            SimpleNamespace(
                                repo_id="test/model",
                                repo_type="model",
                                revisions=(invalid_revision,),
                            ),
                        )
                    )
                ),
            )
            for hub, expected_code in (
                (empty_cache, "MODEL_NOT_CACHED"),
                (invalid_cache, "MODEL_SNAPSHOT_INVALID"),
            ):
                generator = MlxTextGenerator(
                    "test/model", revision, 1024, 128, offline_mode=True
                )
                modules = {
                    "mlx_lm": SimpleNamespace(load=Mock()),
                    "huggingface_hub": hub,
                }
                with (
                    self.subTest(expected_code=expected_code),
                    patch("platform.system", return_value="Darwin"),
                    patch("platform.machine", return_value="arm64"),
                    patch(
                        "importlib.import_module",
                        side_effect=modules.__getitem__,
                    ),
                    self.assertRaises(ApplicationError) as captured,
                ):
                    asyncio.run(generator.prepare())
                self.assertEqual(captured.exception.code, expected_code)

    def test_generates_deterministically_and_strips_reasoning(self) -> None:
        generator = _generator()
        tokenizer = _FakeTokenizer(reject_thinking_option=True)
        generator._model = object()
        generator._tokenizer = tokenizer
        stream_generate = Mock(
            return_value=iter(
                (
                    SimpleNamespace(text="<think>private reasoning</think>\n"),
                    SimpleNamespace(text="# result"),
                )
            )
        )
        sampler = object()
        modules = {
            "mlx_lm": SimpleNamespace(stream_generate=stream_generate),
            "mlx_lm.sample_utils": SimpleNamespace(make_sampler=Mock(return_value=sampler)),
        }
        with patch("importlib.import_module", side_effect=lambda name: modules[name]):
            result = asyncio.run(generator.generate("system", "user", 128))
        self.assertEqual(result, "# result")
        self.assertEqual(tokenizer.template_calls, 2)
        stream_generate.assert_called_once()
        self.assertIs(stream_generate.call_args.kwargs["sampler"], sampler)

    def test_reports_each_generated_piece_to_stream_observer(self) -> None:
        generator = _generator()
        generator._model = object()
        generator._tokenizer = _FakeTokenizer()
        modules = {
            "mlx_lm": SimpleNamespace(
                stream_generate=Mock(
                    return_value=iter(
                        (
                            SimpleNamespace(text="첫 "),
                            SimpleNamespace(text="응답"),
                        )
                    )
                )
            ),
            "mlx_lm.sample_utils": SimpleNamespace(make_sampler=Mock()),
        }
        pieces: list[str] = []
        with patch("importlib.import_module", side_effect=modules.__getitem__):
            result = asyncio.run(
                generator.generate_stream("system", "user", 128, pieces.append)
            )
        self.assertEqual(result, "첫 응답")
        self.assertEqual(pieces, ["첫 ", "응답"])

    def test_stops_stream_generation_at_the_next_token_boundary(self) -> None:
        cancellation = ThreadCancellationToken()
        generator = MlxTextGenerator(
            "test/model",
            "a" * 40,
            1024,
            128,
            cancellation=cancellation,
        )
        generator._model = object()
        generator._tokenizer = _FakeTokenizer()

        def responses():
            yield SimpleNamespace(text="partial")
            cancellation.cancel()
            yield SimpleNamespace(text="must-not-be-returned")

        modules = {
            "mlx_lm": SimpleNamespace(stream_generate=Mock(return_value=responses())),
            "mlx_lm.sample_utils": SimpleNamespace(make_sampler=Mock()),
        }
        with (
            patch("importlib.import_module", side_effect=lambda name: modules[name]),
            self.assertRaises(ApplicationError) as captured,
        ):
            asyncio.run(generator.generate("system", "user", 128))
        self.assertEqual(captured.exception.code, "JOB_CANCELLED")

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
