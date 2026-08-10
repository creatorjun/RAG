# src/enterprise_rag/application/ports/token_counter.py
from typing import Protocol


class TokenCounterPort(Protocol):
    @property
    def identifier(self) -> str:
        raise NotImplementedError

    def count(self, text: str) -> int:
        raise NotImplementedError

    def prefix_end(self, text: str, start: int, maximum_tokens: int) -> int:
        raise NotImplementedError

    def suffix_start(self, text: str, end: int, maximum_tokens: int) -> int:
        raise NotImplementedError
