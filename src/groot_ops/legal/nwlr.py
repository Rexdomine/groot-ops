"""Keeps Lex's use of NWLR Online gentle: an hourly page budget, and reuse of results already verified.

NWLR Online sits behind Cloudflare, which shows a security check when one address loads too many pages.
Lex must never try to pass that check, so the app stays under it instead:

- PageBudget counts every NWLR page Lex opens. A search starts only when the last hour's pages plus what one
  search may need fit the budget, and never while NWLR's last block is still cooling down.
- An identical question asked again within CACHE_DAYS gets its earlier verified result: no pages, no tokens.
- A similar question hands Lex the matching authorities it already verified, so it opens fewer reports.
"""
from __future__ import annotations

import math
import re
from typing import Callable

from groot_ops.legal.store import LegalStore

HOUR = 3600.0
PAGES_PER_HOUR = 12        # NWLR's threshold isn't published; it blocked at 16 pages in an hour on 2026-11-25
PAGES_PER_SEARCH = 8       # a typical search: 1-3 results pages and 3-6 report pages
BLOCK_COOLDOWN = 2 * HOUR  # after NWLR shows its security check, leave it alone this long (1 h proved too short)
CACHE_DAYS = 30
KNOWN_LIMIT = 4
KNOWN_MIN_SHARED = 2
KNOWN_MIN_SCORE = 0.5

_NWLR_OPEN = re.compile(r"agent_browser_open\b.*nwlronline\.com", re.IGNORECASE | re.DOTALL)
_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("""
a an and any are as at be been being but by can could did do does for from had has have how if in into is it its
may might must no not of on or such that the their them then there these they this those to under upon was were what
when where whether which while who whom why will with would shall should against court nigeria nigerian case cases
law laws action actions effect""".split())


def count_pages(actions: list[str]) -> int:
    """NWLR pages Lex loaded, from its browser actions (each open is one page load)."""
    return sum(1 for action in actions if _NWLR_OPEN.search(action))


def words(text: str) -> list[str]:
    """The content words of a question or holding, lower-cased, with a plain plural 's' dropped."""
    out = []
    for word in _WORD.findall((text or "").lower()):
        if len(word) < 4 or word in _STOP:
            continue
        out.append(word[:-1] if word.endswith("s") and not word.endswith("ss") else word)
    return out


def question_key(question: str) -> str:
    return " ".join(_WORD.findall((question or "").lower()))


def citation_key(citation: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (citation or "").lower())


class PageBudget:
    def __init__(self, store: LegalStore, clock: Callable[[], float], pages_per_hour: int = PAGES_PER_HOUR,
                 pages_per_search: int = PAGES_PER_SEARCH, cooldown: float = BLOCK_COOLDOWN):
        self.store, self.clock = store, clock
        self.pages_per_hour, self.pages_per_search, self.cooldown = pages_per_hour, pages_per_search, cooldown

    def wait_seconds(self) -> float:
        """How long until a search may start: 0 when it fits now."""
        now = self.clock()
        blocked_until = self.store.state("blocked_until")
        if blocked_until > now:
            return blocked_until - now
        pages = self.store.page_times(now - HOUR)
        over = len(pages) + self.pages_per_search - self.pages_per_hour
        if over <= 0:
            return 0.0
        # Wait until enough of the oldest pages fall out of the hour.
        return max(0.0, pages[min(over, len(pages)) - 1] + HOUR - now)

    def record(self, pages: int) -> None:
        self.store.record_pages(pages, self.clock())

    def blocked(self) -> None:
        self.store.set_state("blocked_until", self.clock() + self.cooldown)


def waiting_note(seconds: float) -> str:
    minutes = max(1, math.ceil(seconds / 60))
    return f"Waiting for NWLR Online's hourly limit. Your search starts in about {minutes} min."


class ResultCache:
    def __init__(self, store: LegalStore, clock: Callable[[], float], days: int = CACHE_DAYS):
        self.store, self.clock, self.max_age = store, clock, days * 86400

    def answer(self, question: str) -> tuple[dict, float] | None:
        return self.store.cached_answer(question_key(question), self.clock() - self.max_age)

    def known(self, question: str, court_words: str = "") -> list[dict]:
        """Already-verified authorities that share enough of this question's words to be worth offering Lex."""
        asked = set(words(question))
        if len(asked) < KNOWN_MIN_SHARED:
            return []
        scored = []
        for authority, seen in self.store.cached_authorities(self.clock() - self.max_age):
            if court_words and court_words.lower() not in str(authority.get("court", "")).lower():
                continue
            shared = len(asked & seen)
            if shared >= KNOWN_MIN_SHARED and shared / len(asked) >= KNOWN_MIN_SCORE:
                scored.append((shared, authority.get("year") or 0, authority))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [authority for _, _, authority in scored[:KNOWN_LIMIT]]

    def remember(self, question: str, result: dict) -> None:
        if result.get("status") != "ok" or not result.get("authorities"):
            return
        now = self.clock()
        self.store.remember_answer(question_key(question), result, now)
        asked = words(question)
        for authority in result["authorities"]:
            seen = asked + words(authority.get("holding", "")) + words(authority.get("case_name", ""))
            self.store.remember_authority(citation_key(authority.get("citation", "")), authority, seen, now)
