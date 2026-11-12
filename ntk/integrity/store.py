"""Private SQLite state, optimistic revisions, and durable operation claims."""

import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..contracts import AppError
from .contracts import Workspace


class Store:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = directory / "integrity.sqlite3"
        descriptor = (
            os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            if not self.path.exists()
            else None
        )
        if descriptor is not None:
            os.close(descriptor)
        info = self.path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Integrity storage must be a private regular file")
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operations (
                    workspace TEXT NOT NULL, operation TEXT NOT NULL, status TEXT NOT NULL,
                    PRIMARY KEY(workspace, operation)
                );
                CREATE TABLE IF NOT EXISTS allowances (
                    name TEXT PRIMARY KEY, attempts INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS simulated_provider (
                    id TEXT PRIMARY KEY, body TEXT NOT NULL
                );
            """)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, ws: Workspace) -> None:
        with self.connection() as db:
            count = db.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
            if count >= 200:
                raise AppError(
                    "WORKSPACE_LIMIT", "The local demo workspace limit was reached.", 429
                )
            db.execute(
                "INSERT INTO workspaces VALUES (?, ?, ?)",
                (ws.id, ws.revision, ws.model_dump_json()),
            )

    def get(self, workspace_id: str) -> Workspace:
        with self.connection() as db:
            row = db.execute("SELECT body FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "This demo workspace is unavailable.", 404)
        return Workspace.model_validate_json(row[0])

    def save(self, ws: Workspace) -> None:
        original_revision = ws.revision
        candidate = ws.model_copy(update={"revision": original_revision + 1})
        with self.connection() as db:
            cursor = db.execute(
                "UPDATE workspaces SET revision=?, body=? WHERE id=? AND revision=?",
                (candidate.revision, candidate.model_dump_json(), ws.id, original_revision),
            )
            if cursor.rowcount != 1:
                raise AppError(
                    "STATE_CHANGED", "The order changed. Refresh before continuing.", 409
                )
        ws.revision = candidate.revision

    def claim(self, workspace: str, operation: str) -> bool:
        """A committed claim precedes dispatch; an unknown result is never blindly retried."""
        with self.connection() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO operations VALUES (?, ?, 'dispatched')",
                (workspace, operation),
            )
            return cursor.rowcount == 1

    def finish(self, workspace: str, operation: str) -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE operations SET status='verified' WHERE workspace=? AND operation=?",
                (workspace, operation),
            )

    def reserve(self, name: str, limit: int) -> None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO allowances VALUES (?, 0)", (name,))
            cursor = db.execute(
                "UPDATE allowances SET attempts=attempts+1 WHERE name=? AND attempts<?",
                (name, limit),
            )
            if cursor.rowcount != 1:
                raise AppError(
                    "CALL_LIMIT", "The local provider request allowance is exhausted.", 429
                )

    def provider_get(self, resource_id: str) -> str:
        with self.connection() as db:
            row = db.execute(
                "SELECT body FROM simulated_provider WHERE id=?", (resource_id,)
            ).fetchone()
        if row is None:
            raise AppError("PROVIDER_NOT_FOUND", "The simulated payment was not found.", 404)
        return str(row[0])

    def provider_put(self, resource_id: str, body: str) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO simulated_provider VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                (resource_id, body),
            )
