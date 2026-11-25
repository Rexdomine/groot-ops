"""SQLite storage for GrootOps Legal: lawyers, sessions, search threads, searches, saved authorities.

One file, standard library only. Every read and write is scoped to the signed-in lawyer's user id.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from groot_ops.auth import generate_session_token, hash_password, hash_session_token, normalize_email, verify_password

SESSION_SECONDS = 14 * 24 * 3600
TITLE_CHARS = 80

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL, firm TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, title TEXT NOT NULL,
    created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS searches (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL, question TEXT NOT NULL, court TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL, step INTEGER NOT NULL DEFAULT 0, narration TEXT NOT NULL DEFAULT '',
    result TEXT, feedback TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, finished_at REAL
);
CREATE TABLE IF NOT EXISTS saved (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, citation TEXT NOT NULL, authority TEXT NOT NULL,
    search_id TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY (user_id, citation)
);
-- Every NWLR page Lex opened, and when NWLR last blocked us: the hourly page budget reads these.
CREATE TABLE IF NOT EXISTS nwlr_pages (at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS nwlr_state (key TEXT PRIMARY KEY, value REAL NOT NULL);
-- Verified results and authorities, reused so repeat and similar questions open fewer NWLR pages.
-- Only citations, short quotes, holdings and links are kept: never a report's text.
CREATE TABLE IF NOT EXISTS answer_cache (question_key TEXT PRIMARY KEY, result TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS authority_cache (
    citation_key TEXT PRIMARY KEY, authority TEXT NOT NULL, words TEXT NOT NULL, verified_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS nwlr_pages_by_time ON nwlr_pages(at);
CREATE INDEX IF NOT EXISTS threads_by_user ON threads(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS searches_by_thread ON searches(thread_id, created_at);
"""

# A search moves queued -> running -> done | failed. "done" carries a result whose own status may still be
# no_results or login_failed; "failed" means the app itself could not finish it.
ACTIVE = ("queued", "running")


def _title(question: str) -> str:
    question = " ".join(question.split())
    return question if len(question) <= TITLE_CHARS else question[: TITLE_CHARS - 1].rstrip() + "…"


class LegalStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        with self._db() as db:
            db.executescript(SCHEMA)
            # A restart loses the worker that was running these: say so instead of spinning forever.
            db.execute("UPDATE searches SET status='failed', finished_at=? WHERE status IN ('queued','running')", (time.time(),))

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            db = sqlite3.connect(self.path)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            try:
                yield db
                db.commit()
            finally:
                db.close()

    # --- lawyers and sessions -------------------------------------------------------------------
    def add_user(self, email: str, name: str, password: str, firm: str = "") -> str:
        if len(password) < 10:
            raise ValueError("Use a password of at least 10 characters.")
        user_id = str(uuid.uuid4())
        try:
            with self._db() as db:
                db.execute("INSERT INTO users VALUES (?,?,?,?,?,?)",
                           (user_id, normalize_email(email), name.strip(), firm.strip(), hash_password(password), time.time()))
        except sqlite3.IntegrityError:
            raise ValueError("An account with that email already exists.") from None
        return user_id

    def set_password(self, email: str, password: str) -> bool:
        if len(password) < 10:
            raise ValueError("Use a password of at least 10 characters.")
        with self._db() as db:
            changed = db.execute("UPDATE users SET password_hash=? WHERE email=?",
                                 (hash_password(password), normalize_email(email))).rowcount
            db.execute("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE email=?)", (normalize_email(email),))
        return bool(changed)

    def users(self) -> list[dict]:
        with self._db() as db:
            return [dict(r) for r in db.execute("SELECT id, email, name, firm, created_at FROM users ORDER BY created_at")]

    def login(self, email: str, password: str) -> str | None:
        with self._db() as db:
            row = db.execute("SELECT id, password_hash FROM users WHERE email=?", (normalize_email(email),)).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            return None
        token = generate_session_token()
        with self._db() as db:
            db.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (hash_session_token(token), row["id"], time.time() + SESSION_SECONDS))
        return token

    def user_for(self, token: str | None) -> dict | None:
        if not token:
            return None
        with self._db() as db:
            row = db.execute(
                "SELECT u.id, u.email, u.name, u.firm FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash=? AND s.expires_at > ?", (hash_session_token(token), time.time())).fetchone()
        return dict(row) if row else None

    def logout(self, token: str | None) -> None:
        if token:
            with self._db() as db:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (hash_session_token(token),))

    # --- threads and searches -------------------------------------------------------------------
    def new_search(self, user_id: str, question: str, court: str = "", thread_id: str | None = None) -> dict:
        now = time.time()
        search_id = str(uuid.uuid4())
        with self._db() as db:
            if thread_id:
                if not db.execute("SELECT 1 FROM threads WHERE id=? AND user_id=?", (thread_id, user_id)).fetchone():
                    raise KeyError("no such thread")
                db.execute("UPDATE threads SET updated_at=? WHERE id=?", (now, thread_id))
            else:
                thread_id = str(uuid.uuid4())
                db.execute("INSERT INTO threads VALUES (?,?,?,?,?)", (thread_id, user_id, _title(question), now, now))
            db.execute("INSERT INTO searches (id, thread_id, user_id, question, court, status, created_at) VALUES (?,?,?,?,?,?,?)",
                       (search_id, thread_id, user_id, question, court, "queued", now))
        return {"id": search_id, "thread_id": thread_id}

    def threads(self, user_id: str, limit: int = 100) -> list[dict]:
        with self._db() as db:
            return [dict(r) for r in db.execute(
                "SELECT id, title, created_at, updated_at FROM threads WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
                (user_id, limit))]

    def thread(self, user_id: str, thread_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT id, title, created_at, updated_at FROM threads WHERE id=? AND user_id=?",
                             (thread_id, user_id)).fetchone()
            if row is None:
                return None
            searches = [self._search_row(r) for r in db.execute(
                "SELECT * FROM searches WHERE thread_id=? ORDER BY created_at", (thread_id,))]
        return {**dict(row), "searches": searches}

    def delete_thread(self, user_id: str, thread_id: str) -> bool:
        with self._db() as db:
            return bool(db.execute("DELETE FROM threads WHERE id=? AND user_id=?", (thread_id, user_id)).rowcount)

    def search(self, user_id: str | None, search_id: str) -> dict | None:
        with self._db() as db:
            if user_id is None:
                row = db.execute("SELECT * FROM searches WHERE id=?", (search_id,)).fetchone()
            else:
                row = db.execute("SELECT * FROM searches WHERE id=? AND user_id=?", (search_id, user_id)).fetchone()
        return self._search_row(row) if row else None

    def previous_question(self, thread_id: str, before: float) -> str | None:
        with self._db() as db:
            row = db.execute("SELECT question FROM searches WHERE thread_id=? AND created_at < ? ORDER BY created_at DESC LIMIT 1",
                             (thread_id, before)).fetchone()
        return row["question"] if row else None

    def update_search(self, search_id: str, **fields: Any) -> None:
        allowed = {"status", "step", "narration", "result", "finished_at"}
        fields = {k: (json.dumps(v) if k == "result" and v is not None else v) for k, v in fields.items() if k in allowed}
        if fields:
            with self._db() as db:
                db.execute(f"UPDATE searches SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", (*fields.values(), search_id))

    def set_feedback(self, user_id: str, search_id: str, feedback: str) -> bool:
        with self._db() as db:
            return bool(db.execute("UPDATE searches SET feedback=? WHERE id=? AND user_id=?",
                                   (feedback, search_id, user_id)).rowcount)

    @staticmethod
    def _search_row(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["result"] = json.loads(data["result"]) if data.get("result") else None
        return data

    # --- saved authorities ----------------------------------------------------------------------
    def save_authority(self, user_id: str, search_id: str, authority: dict) -> None:
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO saved VALUES (?,?,?,?,?)",
                       (user_id, authority["citation"], json.dumps(authority), search_id, time.time()))

    def unsave_authority(self, user_id: str, citation: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM saved WHERE user_id=? AND citation=?", (user_id, citation))

    def saved(self, user_id: str) -> list[dict]:
        with self._db() as db:
            return [{**json.loads(r["authority"]), "search_id": r["search_id"], "saved_at": r["created_at"]}
                    for r in db.execute("SELECT * FROM saved WHERE user_id=? ORDER BY created_at DESC", (user_id,))]

    # --- NWLR page budget -----------------------------------------------------------------------
    def record_pages(self, count: int, at: float) -> None:
        if count > 0:
            with self._db() as db:
                db.executemany("INSERT INTO nwlr_pages VALUES (?)", [(at,)] * count)

    def page_times(self, since: float) -> list[float]:
        with self._db() as db:
            db.execute("DELETE FROM nwlr_pages WHERE at < ?", (since - 86400,))
            return [r["at"] for r in db.execute("SELECT at FROM nwlr_pages WHERE at > ? ORDER BY at", (since,))]

    def set_state(self, key: str, value: float) -> None:
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO nwlr_state VALUES (?,?)", (key, value))

    def state(self, key: str, default: float = 0.0) -> float:
        with self._db() as db:
            row = db.execute("SELECT value FROM nwlr_state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    # --- verified-result cache ------------------------------------------------------------------
    def cached_answer(self, question_key: str, since: float) -> tuple[dict, float] | None:
        with self._db() as db:
            row = db.execute("SELECT result, created_at FROM answer_cache WHERE question_key=? AND created_at >= ?",
                             (question_key, since)).fetchone()
        return (json.loads(row["result"]), row["created_at"]) if row else None

    def remember_answer(self, question_key: str, result: dict, at: float) -> None:
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO answer_cache VALUES (?,?,?)", (question_key, json.dumps(result), at))

    def remember_authority(self, citation_key: str, authority: dict, words: list[str], at: float) -> None:
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO authority_cache VALUES (?,?,?,?)",
                       (citation_key, json.dumps(authority), " ".join(sorted(set(words))), at))

    def cached_authorities(self, since: float) -> list[tuple[dict, set[str]]]:
        with self._db() as db:
            rows = db.execute("SELECT authority, words FROM authority_cache WHERE verified_at >= ?", (since,)).fetchall()
        return [(json.loads(r["authority"]), set(r["words"].split())) for r in rows]
