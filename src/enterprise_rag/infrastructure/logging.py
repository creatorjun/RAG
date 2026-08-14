from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from enum import Enum
from io import TextIOWrapper
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from enterprise_rag.infrastructure.config.settings import LoggingSettings

try:
    import fcntl
except ModuleNotFoundError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]


_LOGGER_NAME = "enterprise_rag"
_LOG_FILE_NAME = "enterprise-rag.jsonl"
_CONFIGURATION_LOCK = threading.RLock()
_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "authorization",
        "auth_token",
        "completion",
        "model_output",
        "password",
        "prompt",
        "prompt_text",
        "runner_token",
        "secret",
        "source_text",
    }
)
_SENSITIVE_SUFFIXES = ("_api_key", "_auth_token", "_password", "_secret")
_STANDARD_RECORD_FIELDS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"asctime", "message"}


def _is_sensitive_field(name: str) -> bool:
    normalized = name.casefold()
    return normalized in _SENSITIVE_FIELD_NAMES or normalized.endswith(_SENSITIVE_SUFFIXES)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _is_sensitive_field(str(key)) else _json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return repr(value)


class JsonLineFormatter(logging.Formatter):
    """Render one structured, machine-readable JSON object per log record."""

    def __init__(self, component: str) -> None:
        super().__init__()
        self._component = component

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, timezone.utc).isoformat(
            timespec="milliseconds"
        )
        payload: dict[str, Any] = {
            "timestamp": timestamp.replace("+00:00", "Z"),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "component": self._component,
            "process_id": record.process,
            "process_name": record.processName,
            "thread_id": record.thread,
            "thread_name": record.threadName,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        for name, value in sorted(record.__dict__.items()):
            if name in _STANDARD_RECORD_FIELDS or name.startswith("_"):
                continue
            payload[name] = "[REDACTED]" if _is_sensitive_field(name) else _json_safe(value)
        if record.exc_info is not None:
            exception_type, exception, _ = record.exc_info
            payload["exception"] = {
                "type": exception_type.__name__ if exception_type is not None else "Exception",
                "message": str(exception) if exception is not None else "",
                "stack_trace": self.formatException(record.exc_info),
            }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class _ProcessSafeRotatingFileHandler(RotatingFileHandler):
    """Serialize writes and rotation across the GUI, CLI, and worker processes."""

    def __init__(
        self,
        filename: Path,
        maximum_file_bytes: int,
        retained_files: int,
    ) -> None:
        self._lock_path = Path(f"{filename}.lock")
        self._lock_descriptor: int | None = None
        self._enterprise_rag_managed = True
        super().__init__(
            filename,
            mode="a",
            maxBytes=maximum_file_bytes,
            backupCount=retained_files,
            encoding="utf-8",
            delay=True,
        )

    def _open(self) -> TextIOWrapper:
        stream = super()._open()
        try:
            Path(self.baseFilename).chmod(0o600)
        except OSError:
            pass
        return stream

    def emit(self, record: logging.LogRecord) -> None:
        self._acquire_process_lock()
        try:
            self._reopen_if_rotated_by_another_process()
            super().emit(record)
        finally:
            self._release_process_lock()

    def close(self) -> None:
        try:
            super().close()
        finally:
            if self._lock_descriptor is not None:
                try:
                    os.close(self._lock_descriptor)
                except OSError:
                    pass
                self._lock_descriptor = None

    def _acquire_process_lock(self) -> None:
        if fcntl is None:
            return
        if self._lock_descriptor is None:
            self._lock_descriptor = os.open(
                self._lock_path,
                os.O_CREAT | os.O_RDWR,
                0o600,
            )
        fcntl.flock(self._lock_descriptor, fcntl.LOCK_EX)

    def _release_process_lock(self) -> None:
        if fcntl is not None and self._lock_descriptor is not None:
            fcntl.flock(self._lock_descriptor, fcntl.LOCK_UN)

    def _reopen_if_rotated_by_another_process(self) -> None:
        if self.stream is None:
            return
        try:
            opened = os.fstat(self.stream.fileno())
            current = Path(self.baseFilename).stat()
        except OSError:
            self.stream.close()
            self.stream = None
            return
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            self.stream.close()
            self.stream = self._open()


def configure_logging(
    log_directory: Path,
    settings: LoggingSettings,
    component: str,
) -> Path:
    """Configure the application logger and return the active JSONL log path."""

    log_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    log_path = log_directory / _LOG_FILE_NAME
    handler = _ProcessSafeRotatingFileHandler(
        log_path,
        settings.maximum_file_bytes,
        settings.retained_files,
    )
    handler.setLevel(settings.level)
    handler.setFormatter(JsonLineFormatter(component))

    logger = logging.getLogger(_LOGGER_NAME)
    with _CONFIGURATION_LOCK:
        previous_handlers = [
            existing
            for existing in logger.handlers
            if getattr(existing, "_enterprise_rag_managed", False)
        ]
        for existing in previous_handlers:
            logger.removeHandler(existing)
            existing.close()
        logger.setLevel(settings.level)
        logger.propagate = False
        logger.addHandler(handler)

    logger.info(
        "logging_configured",
        extra={
            "log_path": str(log_path),
            "configured_level": settings.level,
            "maximum_file_bytes": settings.maximum_file_bytes,
            "retained_files": settings.retained_files,
        },
    )
    return log_path


def shutdown_logging() -> None:
    """Flush and close handlers owned by the application logging module."""

    logger = logging.getLogger(_LOGGER_NAME)
    with _CONFIGURATION_LOCK:
        for handler in tuple(logger.handlers):
            if getattr(handler, "_enterprise_rag_managed", False):
                logger.removeHandler(handler)
                handler.close()
