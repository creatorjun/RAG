# src/enterprise_rag/application/ports/clock.py
from datetime import datetime
from typing import Protocol


class ClockPort(Protocol):
    def now(self) -> datetime:
        raise NotImplementedError


class IdGeneratorPort(Protocol):
    def new_id(self) -> str:
        raise NotImplementedError
