from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from enterprise_rag.application.dto.progress import ProgressEventDto
from enterprise_rag.application.ports.clock import ClockPort
from enterprise_rag.domain.errors import ApplicationError, revision_error
from enterprise_rag.domain.jobs import DocumentJob, DocumentJobState
from enterprise_rag.infrastructure.workspace.path_security import is_link_or_reparse

_SCHEMA_VERSION = 1
_MIGRATION_SQL = """
CREATE TABLE document_job (
    job_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    last_event_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_event_sequence >= 0),
    last_percentage INTEGER NOT NULL DEFAULT 0 CHECK (last_percentage BETWEEN 0 AND 100),
    record_version INTEGER NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE job_progress_event (
    job_id TEXT NOT NULL REFERENCES document_job(job_id) ON DELETE RESTRICT,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    stage TEXT NOT NULL,
    message TEXT NOT NULL,
    counter_name TEXT,
    completed INTEGER CHECK (completed IS NULL OR completed >= 0),
    total INTEGER CHECK (total IS NULL OR total >= 1),
    overall_percentage INTEGER CHECK (
        overall_percentage IS NULL OR overall_percentage BETWEEN 0 AND 99
    ),
    occurred_at TEXT NOT NULL,
    PRIMARY KEY (job_id, sequence),
    CHECK ((completed IS NULL) = (total IS NULL)),
    CHECK (completed IS NULL OR completed <= total)
);

CREATE INDEX ix_job_progress_event_job
ON job_progress_event(job_id, sequence);
"""
_MIGRATION_CHECKSUM = hashlib.sha256(_MIGRATION_SQL.encode("utf-8")).hexdigest()


class SqliteDocumentJobRepository:
    def __init__(self, database_path: Path, clock: ClockPort) -> None:
        self._database_path = database_path.expanduser()
        self._clock = clock
        self._prepare_path()
        self._migrate()

    async def create(self, job: DocumentJob) -> None:
        await asyncio.to_thread(self._create, job)

    async def get(self, job_id: str) -> DocumentJob | None:
        return await asyncio.to_thread(self._get, job_id)

    async def list_recent(self, limit: int = 100) -> tuple[DocumentJob, ...]:
        return await asyncio.to_thread(self._list_recent, limit)

    async def transition(
        self,
        job_id: str,
        expected: DocumentJobState,
        target: DocumentJobState,
    ) -> DocumentJob:
        return await asyncio.to_thread(self._transition, job_id, expected, target)

    async def publish(self, event: ProgressEventDto) -> None:
        await asyncio.to_thread(self._publish, event)

    async def list_after(
        self,
        job_id: str,
        after_sequence: int = 0,
    ) -> tuple[ProgressEventDto, ...]:
        return await asyncio.to_thread(self._list_after, job_id, after_sequence)

    def close(self) -> None:
        return None

    def _prepare_path(self) -> None:
        try:
            if is_link_or_reparse(self._database_path):
                raise revision_error("LINK_NOT_ALLOWED")
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            if is_link_or_reparse(self._database_path.parent):
                raise revision_error("LINK_NOT_ALLOWED")
            self._database_path = self._database_path.resolve(strict=False)
        except ApplicationError:
            raise
        except OSError as error:
            raise revision_error("IO_FAILURE") from error

    def _migrate(self) -> None:
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migration (
                        version INTEGER PRIMARY KEY CHECK (version >= 1),
                        checksum TEXT NOT NULL,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                rows = connection.execute(
                    "SELECT version, checksum FROM schema_migration ORDER BY version"
                ).fetchall()
                if rows:
                    if len(rows) != 1 or rows[0]["version"] != _SCHEMA_VERSION:
                        raise revision_error("DATABASE_SCHEMA_INVALID")
                    if rows[0]["checksum"] != _MIGRATION_CHECKSUM:
                        raise revision_error("DATABASE_SCHEMA_INVALID")
                    self._verify_schema(connection)
                    return
                connection.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + _MIGRATION_SQL
                    + "\n"
                    + "INSERT INTO schema_migration(version, checksum, applied_at) VALUES ("
                    + f"{_SCHEMA_VERSION}, '{_MIGRATION_CHECKSUM}', "
                    + f"'{self._utc_now()}');\nCOMMIT;"
                )
                self._verify_schema(connection)
        except ApplicationError:
            raise
        except sqlite3.Error as error:
            raise revision_error("DATABASE_SCHEMA_INVALID") from error

    @staticmethod
    def _verify_schema(connection: sqlite3.Connection) -> None:
        required = {"document_job", "job_progress_event", "schema_migration"}
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        if not required.issubset({row["name"] for row in rows}):
            raise revision_error("DATABASE_SCHEMA_INVALID")

    def _create(self, job: DocumentJob) -> None:
        now = self._utc_now()
        try:
            with self._transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO document_job(
                        job_id, state, last_event_sequence, last_percentage,
                        record_version, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        job.job_id,
                        job.state.value,
                        job.last_event_sequence,
                        job.last_percentage,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise revision_error("JOB_ALREADY_EXISTS", {"job_id": job.job_id}) from error
        except sqlite3.Error as error:
            raise revision_error("IO_FAILURE", {"job_id": job.job_id}) from error

    def _get(self, job_id: str) -> DocumentJob | None:
        self._validate_job_id(job_id)
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM document_job WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
        except sqlite3.Error as error:
            raise revision_error("IO_FAILURE", {"job_id": job_id}) from error
        return None if row is None else self._to_job(row)

    def _list_recent(self, limit: int) -> tuple[DocumentJob, ...]:
        if not 1 <= limit <= 1000:
            raise revision_error("INVALID_INPUT", {"field": "limit"})
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    """
                    SELECT * FROM document_job
                    ORDER BY created_at DESC, job_id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.Error as error:
            raise revision_error("IO_FAILURE") from error
        return tuple(self._to_job(row) for row in rows)

    def _transition(
        self,
        job_id: str,
        expected: DocumentJobState,
        target: DocumentJobState,
    ) -> DocumentJob:
        self._validate_job_id(job_id)
        try:
            with self._transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM document_job WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
                if row is None:
                    raise revision_error("JOB_NOT_FOUND", {"job_id": job_id})
                job = self._to_job(row)
                if job.state is not expected:
                    raise revision_error("JOB_STATE_CONFLICT", {"job_id": job_id})
                try:
                    updated = job.transition(target)
                except ValueError as error:
                    raise revision_error("JOB_STATE_CONFLICT", {"job_id": job_id}) from error
                cursor = connection.execute(
                    """
                    UPDATE document_job
                    SET state = ?, last_percentage = ?, record_version = record_version + 1,
                        updated_at = ?
                    WHERE job_id = ? AND state = ? AND record_version = ?
                    """,
                    (
                        updated.state.value,
                        updated.last_percentage,
                        self._utc_now(),
                        job_id,
                        expected.value,
                        row["record_version"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise revision_error("JOB_STATE_CONFLICT", {"job_id": job_id})
                return updated
        except ApplicationError:
            raise
        except sqlite3.Error as error:
            raise revision_error("IO_FAILURE", {"job_id": job_id}) from error

    def _publish(self, event: ProgressEventDto) -> None:
        if event.job_id is None or event.sequence is None:
            raise revision_error("PROGRESS_EVENT_CONFLICT")
        self._validate_job_id(event.job_id)
        occurred_at = event.occurred_at or self._utc_now()
        try:
            with self._transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM document_job WHERE job_id = ?",
                    (event.job_id,),
                ).fetchone()
                if row is None:
                    raise revision_error("JOB_NOT_FOUND", {"job_id": event.job_id})
                job = self._to_job(row)
                try:
                    updated = job.record_progress(event.sequence, event.percentage)
                except ValueError as error:
                    raise revision_error(
                        "PROGRESS_EVENT_CONFLICT",
                        {"job_id": event.job_id},
                    ) from error
                connection.execute(
                    """
                    INSERT INTO job_progress_event(
                        job_id, sequence, stage, message, counter_name,
                        completed, total, overall_percentage, occurred_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.job_id,
                        event.sequence,
                        event.stage,
                        event.message,
                        event.counter_name,
                        event.completed,
                        event.total,
                        event.percentage,
                        occurred_at,
                    ),
                )
                cursor = connection.execute(
                    """
                    UPDATE document_job
                    SET last_event_sequence = ?, last_percentage = ?,
                        record_version = record_version + 1, updated_at = ?
                    WHERE job_id = ? AND record_version = ?
                    """,
                    (
                        updated.last_event_sequence,
                        updated.last_percentage,
                        occurred_at,
                        event.job_id,
                        row["record_version"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise revision_error(
                        "PROGRESS_EVENT_CONFLICT",
                        {"job_id": event.job_id},
                    )
        except ApplicationError:
            raise
        except sqlite3.IntegrityError as error:
            raise revision_error(
                "PROGRESS_EVENT_CONFLICT",
                {"job_id": event.job_id},
            ) from error
        except sqlite3.Error as error:
            raise revision_error("IO_FAILURE", {"job_id": event.job_id}) from error

    def _list_after(
        self,
        job_id: str,
        after_sequence: int,
    ) -> tuple[ProgressEventDto, ...]:
        self._validate_job_id(job_id)
        if after_sequence < 0:
            raise revision_error("PROGRESS_EVENT_CONFLICT", {"job_id": job_id})
        try:
            with self._connection() as connection:
                exists = connection.execute(
                    "SELECT 1 FROM document_job WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
                if exists is None:
                    raise revision_error("JOB_NOT_FOUND", {"job_id": job_id})
                rows = connection.execute(
                    """
                    SELECT * FROM job_progress_event
                    WHERE job_id = ? AND sequence > ?
                    ORDER BY sequence
                    """,
                    (job_id, after_sequence),
                ).fetchall()
        except ApplicationError:
            raise
        except sqlite3.Error as error:
            raise revision_error("IO_FAILURE", {"job_id": job_id}) from error
        return tuple(
            ProgressEventDto(
                percentage=row["overall_percentage"],
                stage=row["stage"],
                message=row["message"],
                completed=row["completed"],
                total=row["total"],
                counter_name=row["counter_name"],
                job_id=row["job_id"],
                sequence=row["sequence"],
                occurred_at=row["occurred_at"],
            )
            for row in rows
        )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA journal_mode = WAL")
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")

    @staticmethod
    def _to_job(row: sqlite3.Row) -> DocumentJob:
        try:
            return DocumentJob(
                job_id=row["job_id"],
                state=DocumentJobState(row["state"]),
                last_event_sequence=row["last_event_sequence"],
                last_percentage=row["last_percentage"],
            )
        except (ValueError, KeyError) as error:
            raise revision_error("DATABASE_SCHEMA_INVALID") from error

    @staticmethod
    def _validate_job_id(job_id: str) -> None:
        try:
            DocumentJob(job_id)
        except ValueError as error:
            raise revision_error("INVALID_JOB_ID", {"job_id": job_id}) from error

    def _utc_now(self) -> str:
        return self._clock.now().isoformat().replace("+00:00", "Z")
