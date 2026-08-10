# src/enterprise_rag/infrastructure/clock/system.py
from datetime import datetime, timezone
from uuid import uuid4


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class UuidIdGenerator:
    def new_id(self) -> str:
        return uuid4().hex
