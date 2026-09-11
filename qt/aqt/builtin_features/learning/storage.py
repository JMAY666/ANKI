# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Profile-local durable task ledger. No learning history is stored or edited here."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from aqt.builtin_features.storage import read_object, write_object

from .policy import DEFAULT_SETTINGS, REQUEST_RESERVE, validate_settings


class LearningStore:
    def __init__(self, profile: Path):
        self.root = profile / "LearningWorkspace"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "history.sqlite"
        self.settings_path = self.root / "settings.json"
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY, day TEXT NOT NULL, scope TEXT NOT NULL,
                    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    created INTEGER NOT NULL, updated INTEGER NOT NULL,
                    snapshot TEXT, report TEXT, error TEXT NOT NULL DEFAULT '',
                    cost REAL NOT NULL DEFAULT 0,
                    UNIQUE(day,scope)
                );
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY, report_id TEXT NOT NULL, deck_id INTEGER NOT NULL,
                    status TEXT NOT NULL, created INTEGER NOT NULL,
                    before_value TEXT NOT NULL, after_value TEXT NOT NULL,
                    reason TEXT NOT NULL, error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, started INTEGER NOT NULL, ended INTEGER,
                    deck_id INTEGER NOT NULL, deck_name TEXT NOT NULL, events TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS charges (
                    report_id TEXT NOT NULL, attempt INTEGER NOT NULL,
                    created INTEGER NOT NULL, cost REAL NOT NULL, settled INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(report_id,attempt)
                );
            """)
            db.execute(
                "INSERT OR IGNORE INTO charges SELECT id,attempts,updated,cost,1 FROM reports WHERE NOT EXISTS (SELECT 1 FROM charges WHERE report_id=reports.id)"
            )

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def settings(self) -> dict[str, Any]:
        return (
            validate_settings(read_object(self.settings_path))
            if self.settings_path.exists()
            else dict(DEFAULT_SETTINGS)
        )

    def save_settings(self, value: dict[str, Any]) -> None:
        write_object(self.settings_path, validate_settings(value))

    def claim(
        self, day: str, scope: str, budget: float, now: int, *, manual: bool = False
    ) -> str | None:
        """Reserve cost before dispatch; stale in-flight requests are never replayed automatically."""
        month_start = time.mktime(time.localtime(now)[:2] + (1, 0, 0, 0, 0, 0, -1))
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM reports WHERE day=? AND scope=?", (day, scope)
            ).fetchone()
            if row:
                if row["status"] == "running" or (
                    not manual
                    and (
                        row["status"] != "retry"
                        or row["attempts"] >= 3
                        or now - row["updated"] < 900
                    )
                ):
                    return None
                # Applied/pending reports remain immutable audit evidence.
                if db.execute(
                    "SELECT 1 FROM actions WHERE report_id=?", (row["id"],)
                ).fetchone():
                    return None
            spent = db.execute(
                "SELECT COALESCE(SUM(cost),0) FROM charges WHERE created>=?",
                (month_start,),
            ).fetchone()[0]
            if spent + REQUEST_RESERVE > budget:
                raise ValueError("已达到月预算，未发送请求")
            if row:
                db.execute(
                    "UPDATE reports SET status='running', attempts=attempts+1, updated=?, cost=cost+?, error='' WHERE id=?",
                    (now, REQUEST_RESERVE, row["id"]),
                )
                db.execute(
                    "INSERT INTO charges(report_id,attempt,created,cost) VALUES(?,?,?,?)",
                    (row["id"], row["attempts"] + 1, now, REQUEST_RESERVE),
                )
                return row["id"]
            key = uuid.uuid4().hex
            db.execute(
                "INSERT INTO reports(id,day,scope,status,attempts,created,updated,cost) VALUES(?,?,?,'running',1,?,?,?)",
                (key, day, scope, now, now, REQUEST_RESERVE),
            )
            db.execute(
                "INSERT INTO charges(report_id,attempt,created,cost) VALUES(?,1,?,?)",
                (key, now, REQUEST_RESERVE),
            )
            return key

    def finish(
        self,
        key: str,
        status: str,
        snapshot: dict,
        report: dict | None = None,
        error: str = "",
        cost: float | None = None,
        expected_attempt: int | None = None,
    ) -> None:
        with self.connection() as db:
            current = db.execute(
                "SELECT attempts FROM reports WHERE id=?", (key,)
            ).fetchone()
            if current is None:
                return
            attempt = current[0] if expected_attempt is None else expected_attempt
            db.execute(
                "UPDATE charges SET cost=COALESCE(?,cost),settled=1 WHERE report_id=? AND attempt=? AND settled=0",
                (cost, key, attempt),
            )
            db.execute(
                "UPDATE reports SET cost=(SELECT COALESCE(SUM(cost),0) FROM charges WHERE report_id=?) WHERE id=?",
                (key, key),
            )
            db.execute(
                "UPDATE reports SET status=?,snapshot=?,report=?,error=?,updated=? WHERE id=? AND attempts=?",
                (
                    status,
                    json.dumps(snapshot, ensure_ascii=False),
                    json.dumps(report, ensure_ascii=False),
                    error,
                    int(time.time()),
                    key,
                    attempt,
                ),
            )

    def reports(self) -> list[dict]:
        with self.connection() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM reports ORDER BY updated DESC LIMIT 100"
                )
            ]

    def report(self, key: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT * FROM reports WHERE id=?", (key,)).fetchone()
            if row is None:
                raise ValueError("报告不存在")
            return dict(row)

    def actions(self) -> list[dict]:
        with self.connection() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM actions ORDER BY created DESC")
            ]

    def pending_action(
        self,
        report_id: str,
        deck_id: int,
        before: Any,
        after: Any,
        reason: str,
        now: int,
    ) -> str:
        key = uuid.uuid4().hex
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM actions WHERE report_id=? AND status!='failed'",
                (report_id,),
            ).fetchone():
                raise ValueError("这份报告已经应用或正在核对，不能重复应用")
            db.execute(
                "INSERT INTO actions VALUES(?,?,?,'pending',?,?,?,?, '')",
                (
                    key,
                    report_id,
                    deck_id,
                    now,
                    json.dumps(before),
                    json.dumps(after),
                    reason,
                ),
            )
        return key

    def mark_action(self, key: str, status: str, error: str = "") -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE actions SET status=?,error=? WHERE id=?", (status, error, key)
            )

    def save_session(
        self,
        key: str,
        started: int,
        deck_id: int,
        name: str,
        events: list[int],
        ended: int | None = None,
    ) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET events=excluded.events,ended=excluded.ended",
                (key, started, ended, deck_id, name, json.dumps(events)),
            )

    def sessions(self) -> list[dict]:
        with self.connection() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM sessions ORDER BY started DESC LIMIT 50"
                )
            ]
