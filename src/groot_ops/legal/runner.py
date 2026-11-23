"""Runs lawyers' searches one at a time through Lex, and turns Lex's chat activity into progress steps.

Lex researches in a single chat, so searches queue. While one runs, every poll reads Lex's newest messages
(through the local OpenMausBot API) to move the progress trail: signing in -> searching -> reading -> checking.
"""
from __future__ import annotations

import dataclasses
import logging
import queue
import re
import threading
import time
from typing import Callable
from urllib.parse import unquote_plus

from groot_ops.case_search import CaseSearch
from groot_ops.legal.store import LegalStore
from groot_ops.telegram_channel import http_json

log = logging.getLogger("groot_ops.legal.runner")

STEPS = ("Signing in to NWLR Online", "Searching NWLR Online", "Reading the cases", "Checking every citation")
COURTS = {"": "", "supreme": "the Supreme Court", "appeal": "the Court of Appeal", "high": "the High Courts"}
_SEARCHING = re.compile(r"\b(search|keyword|phrasing|query|queries)", re.IGNORECASE)
_READING = re.compile(r"\b(open(ed|ing)?|read(ing)?|judgment|case page|holding|ratio)\b", re.IGNORECASE)
NARRATION_CHARS = 160


def compose_question(question: str, court: str = "", previous: str | None = None) -> str:
    """What Lex is asked: the lawyer's words, the court limit, and the earlier question for a follow-up."""
    parts = []
    if previous:
        parts.append(f"Earlier question in this matter: {previous}. Follow-up:")
    parts.append(question.strip())
    if COURTS.get(court):
        parts.append(f"Only cite authorities from {COURTS[court]}.")
    return " ".join(parts)


_SEARCH_TERM = re.compile(r"[?&]search_term=([^&\"\s]+)")


def step_from(texts: list[str], current: int, actions: list[str] = ()) -> int:
    """Progress only moves forward, as far as Lex's notes or its browser actions show."""
    step = current
    for text in texts:
        if step < 1 and _SEARCHING.search(text):
            step = 1
        if step >= 1 and _READING.search(text):
            step = max(step, 2)
    for action in actions:
        if "search_term=" in action:
            step = max(step, 1)
        elif "/dashboard/legal-research/" in action or "const K=" in action:
            step = max(step, 2)
    return step


def describe(actions: list[str]) -> str:
    """A plain note for the lawyer from Lex's latest browser action, for when Lex works without commentary."""
    reports = sum(1 for a in actions if "const K=" in a)
    for action in reversed(actions):
        term = _SEARCH_TERM.search(action)
        if term:
            return f"Searching: {unquote_plus(term.group(1))}"[:NARRATION_CHARS]
        if "const K=" in action or "/dashboard/legal-research/" in action:
            return f"Reading report {max(reports, 1)}"
    return ""


class LexWatcher:
    """Reads Lex's chat after a point in time: its notes, and its browser actions (tool name and input)."""

    def __init__(self, api_base: str, bot_id: str, call: Callable = http_json):
        self.api_base, self.bot_id, self._call = api_base.rstrip("/"), bot_id, call
        self._thread: str | None = None

    def poll(self, since_ms: int) -> tuple[list[str], list[str]]:
        if not self._thread:
            status, bot = self._call(f"{self.api_base}/api/bots/{self.bot_id}")
            self._thread = (bot.get("bot") or bot).get("mainThreadId") if status < 300 else None
            if not self._thread:
                return [], []
        status, page = self._call(f"{self.api_base}/api/threads/{self._thread}/messages")
        if status >= 300:
            return [], []
        texts, actions = [], []
        for m in page.get("messages") or []:
            if m.get("role") != "bot" or int(m.get("at") or 0) < since_ms:
                continue
            if m.get("kind") == "text" and str(m.get("text") or "").strip():
                texts.append(str(m["text"]).strip())
            elif m.get("kind") == "activity" and isinstance(m.get("tool"), dict):
                actions.append(f"{m['tool'].get('name', '')} {str(m['tool'].get('input') or '')[:600]}")
        return texts, actions

    def texts_since(self, since_ms: int) -> list[str]:
        return self.poll(since_ms)[0]


def result_dict(result) -> dict:
    return dataclasses.asdict(result)


class SearchRunner:
    def __init__(self, store: LegalStore, search: CaseSearch, watcher: LexWatcher | None,
                 clock: Callable[[], float] = time.time):
        self.store, self.case_search, self.watcher, self.clock = store, search, watcher, clock
        self._queue: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        if self._worker is None:
            self._worker = threading.Thread(target=self._loop, name="legal-search", daemon=True)
            self._worker.start()

    def submit(self, search_id: str) -> None:
        self._queue.put(search_id)

    def queued_ahead(self) -> int:
        return self._queue.qsize()

    def _loop(self) -> None:
        while True:
            search_id = self._queue.get()
            try:
                self.run(search_id)
            except Exception:
                log.exception("search %s failed", search_id)
                self.store.update_search(search_id, status="failed", finished_at=self.clock())

    def run(self, search_id: str) -> None:
        search = self.store.search(None, search_id)
        if search is None:
            return
        previous = self.store.previous_question(search["thread_id"], search["created_at"])
        question = compose_question(search["question"], search["court"], previous)
        started_ms = int(self.clock() * 1000)
        state = {"step": 0, "narration": ""}
        self.store.update_search(search_id, status="running", step=0, narration="")

        def on_wait() -> None:
            if self.watcher is None:
                return
            try:
                if hasattr(self.watcher, "poll"):
                    texts, actions = self.watcher.poll(started_ms)
                else:
                    texts, actions = self.watcher.texts_since(started_ms), []
            except Exception:
                return
            step = step_from(texts, state["step"], actions)
            # Lex works without commentary, so its own words are rare: fall back to what it is doing.
            latest = texts[-1] if texts and not texts[-1].lstrip().startswith("```") else ""
            narration = (latest[:NARRATION_CHARS] or describe(actions)) or state["narration"]
            if step != state["step"] or narration != state["narration"]:
                state.update(step=step, narration=narration)
                self.store.update_search(search_id, step=step, narration=narration)

        result = self.case_search.search(question, on_wait=on_wait)
        self.store.update_search(search_id, step=3)
        self.store.update_search(search_id, status="done", result=result_dict(result), finished_at=self.clock())
