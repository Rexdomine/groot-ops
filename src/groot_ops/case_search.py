"""Case Search: plain-English legal research over NWLR Online, run by the Lex bot on OpenMausBot.

Flow for one question:
    caller -> CaseSearch.search(question)
           -> Lex's main chat through the local OpenMausBot API (Lex signs in to NWLR Online in its own
              browser with the firm's saved login, searches, reads the cases)
           -> Lex's final message is one JSON block
           -> parse_reply() + verify() keep only authorities with a well-formed citation, a verbatim quote
              and a case-page address on an allowed law-report site; everything else is reported as rejected
           -> format_for_chat() / format_markdown()

The point of verify(): a lawyer may file what we return, so nothing reaches them without a citation in a
recognised Nigerian law-report format and a link back to the page Lex read.

Standard library only, so it runs in the bridge on the VPS without extra installs.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import unquote, urlsplit

from groot_ops.telegram_channel import OpsChat, http_json

log = logging.getLogger("groot_ops.case_search")

NWLR_HOST = "nwlronline.com"
NWLR_LOGIN_URL = "https://nwlronline.com/auth/login"
ALLOWED_SOURCE_HOSTS = (NWLR_HOST,)
# Pages that can never be the case Lex read.
NON_CASE_PATHS = {"", "/", "/auth/login", "/dashboard", "/dashboard/legal-research", "/search-feedback"}

STATUSES = {"ok", "no_results", "login_failed", "site_error", "rate_limited"}
_RATE_LIMIT_WORDS = re.compile(r"rate.?limit|\b429\b|security (check|verification)|cloudflare", re.IGNORECASE)
MAX_AUTHORITIES = 10
MAX_QUOTE_WORDS = 120
MAX_QUESTION_CHARS = 2000
SEARCH_TIMEOUT = 15 * 60

# Nigerian law-report citations, e.g. "(2019) 4 NWLR (Pt. 1662) 242", "(2017) LPELR-42345(SC)",
# "(2010) All FWLR (Pt. 520) 1", "(2008) 5 SC (Pt. II) 1", "(1976) 6 SC 1", "(2012) 2 SCM 1".
_CITATION_PATTERNS = (
    r"\(\d{4}\)\s*\d+\s*NWLR\s*\(\s*Pt\.?\s*\d+\s*\)\s*\d+",
    r"\(\d{4}\)\s*LPELR\s*-\s*\d+\s*\(\s*[A-Z]{2,4}\s*\)",
    r"\(\d{4}\)\s*All\s*FWLR\s*\(\s*Pt\.?\s*\d+\s*\)\s*\d+",
    r"\(\d{4}\)\s*\d+\s*(?:SC|SCNJ|SCM|SCNLR|NSCC|NLR|WRN|FWLR)\s*(?:\(\s*Pt\.?\s*[\dIVX]+\s*\)\s*)?\d+",
)
CITATION_RE = re.compile(r"^\s*(?:" + "|".join(_CITATION_PATTERNS) + r")(?:\s*(?:at|@)\s*[\w\-–, ]+)?\s*$", re.IGNORECASE)
_SQUARE_YEAR = re.compile(r"^\s*\[(\d{4})\]")
# Headnote catchlines read "Topic - Subtopic - Whether ...": the publisher's index, not the court's words.
_CATCHLINE = re.compile(r"\S\s+-\s+\S.*\S\s+-\s+\S")
_SIGN_IN_WORDS = re.compile(r"\b(sign(ed)?[ -]?in|log(ged)?[ -]?in|saved login|credentials?)\b", re.IGNORECASE)
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

REQUEST_TEMPLATE = (
    "[Case Search request from a lawyer at a GrootOps pilot firm. Follow your standing research steps on "
    "NWLR Online and reply with the JSON block only.]\n\n"
    "Question: {question}"
)


@dataclass
class Authority:
    case_name: str
    citation: str
    court: str
    year: int | None
    holding: str
    quote: str
    source_url: str
    page: str = ""


@dataclass
class Rejected:
    label: str
    reason: str


@dataclass
class SearchResult:
    status: str
    answer: str = ""
    authorities: list[Authority] = field(default_factory=list)
    statutes: list[dict[str, str]] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    searches_run: list[str] = field(default_factory=list)
    note: str = ""


KNOWN_FIELDS = ("case_name", "citation", "court", "year", "holding", "quote", "page", "source_url")
KNOWN_HEADER = (
    "\n\nKnown authorities (you opened and verified these for earlier questions; use any that answer this "
    "question as given, without opening them again, and open reports only for what is still missing):"
)


def build_request(question: str, known: list[dict] = ()) -> str:
    question = re.sub(r"\s+", " ", question or "").strip()
    if not question:
        raise ValueError("Ask a research question.")
    if len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"Keep the question under {MAX_QUESTION_CHARS} characters.")
    request = REQUEST_TEMPLATE.format(question=question)
    lines = [json.dumps({k: a.get(k) for k in KNOWN_FIELDS if a.get(k) not in (None, "")}, ensure_ascii=False)
             for a in known if isinstance(a, dict)]
    return request + (KNOWN_HEADER + "\n" + "\n".join(lines) if lines else "")


def _text(value, limit: int = 1000) -> str:
    value = "" if value is None else str(value)
    return re.sub(r"\s+", " ", value).strip()[:limit]


def parse_reply(reply: str | None) -> tuple[dict | None, str]:
    """The last JSON object in Lex's reply (fenced or bare), or (None, reason)."""
    if not reply or not reply.strip():
        return None, "Lex gave no reply."
    candidates = _JSON_BLOCK.findall(reply)
    if not candidates:
        start, end = reply.find("{"), reply.rfind("}")
        candidates = [reply[start:end + 1]] if 0 <= start < end else []
    for raw in reversed(candidates):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data, ""
    return None, "Lex's reply had no readable JSON block."


def check_source_url(url: str) -> str | None:
    """None if the address is a case page on an allowed site, else why not."""
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        return "source link is missing or not https"
    if not any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_SOURCE_HOSTS):
        return f"source link is not on {', '.join(ALLOWED_SOURCE_HOSTS)}"
    if parts.path.rstrip("/") in NON_CASE_PATHS:
        return "source link is a search or home page, not a case page"
    return None


_NWLR_CITE = re.compile(r"NWLR\s*\(\s*Pt\.?\s*(\d+)\s*\)\s*(\d+)", re.IGNORECASE)
_NWLR_CASE_ID = re.compile(r"^(\d+)_\d+_(\d+)$")


def link_mismatch(citation: str, url: str) -> str | None:
    """NWLR case pages are /dashboard/legal-research/<base64 of 'Part_x_Page'>: the link must be the cited report."""
    cite = _NWLR_CITE.search(citation or "")
    if not cite:
        return None
    slug = unquote(urlsplit(url or "").path.rstrip("/").rsplit("/", 1)[-1])
    try:
        decoded = base64.b64decode(slug + "=" * (-len(slug) % 4), validate=True).decode("ascii")
    except (ValueError, UnicodeDecodeError):
        return None
    page = _NWLR_CASE_ID.match(decoded)
    if not page or (page.group(1), page.group(2)) == (cite.group(1), cite.group(2)):
        return None
    return f"link opens (Pt. {page.group(1)}) {page.group(2)}, not the cited (Pt. {cite.group(1)}) {cite.group(2)}"


def check_authority(item: dict) -> tuple[Authority | None, str]:
    case_name = _text(item.get("case_name"), 300)
    citation = _SQUARE_YEAR.sub(r"(\1)", _text(item.get("citation"), 120))
    quote = _text(item.get("quote"), 2000)
    source_url = _text(item.get("source_url"), 500)
    if not case_name:
        return None, "no case name"
    if not CITATION_RE.match(citation):
        return None, f"citation '{citation or 'missing'}' is not in a recognised law-report format"
    if not quote:
        return None, "no verbatim quote"
    if _CATCHLINE.search(quote):
        return None, "quote is a headnote catchline, not the court's words"
    if len(quote.split()) > MAX_QUOTE_WORDS:
        return None, "quote is too long to be a pinpoint passage"
    source_problem = check_source_url(source_url) or link_mismatch(citation, source_url)
    if source_problem:
        return None, source_problem
    year = item.get("year")
    try:
        year = int(year) if year not in (None, "") else None
    except (TypeError, ValueError):
        year = None
    match = re.match(r"\s*\((\d{4})\)", citation)
    if match and year and year != int(match.group(1)):
        return None, f"year {year} does not match the citation"
    return Authority(
        case_name=case_name, citation=citation, court=_text(item.get("court"), 80),
        year=year or (int(match.group(1)) if match else None), holding=_text(item.get("holding"), 600),
        quote=quote, source_url=source_url, page=_text(item.get("page"), 60),
    ), ""


def _citation_key(citation: str) -> str:
    return re.sub(r"[\s.]+", "", citation).lower()


def verify(data: dict | None, problem: str = "") -> SearchResult:
    """Turn Lex's JSON into a SearchResult, keeping only authorities that pass every check."""
    if data is None:
        return SearchResult(status="site_error", note=problem or "No result from Lex.")
    status = _text(data.get("status"), 20).lower()
    status = status if status in STATUSES else "site_error"
    result = SearchResult(
        status=status, answer=_text(data.get("answer"), 1500), note=_text(data.get("note"), 600),
        searches_run=[_text(s, 200) for s in (data.get("searches_run") or []) if _text(s)][:12],
    )
    seen: set[str] = set()
    for item in (data.get("authorities") or [])[:MAX_AUTHORITIES * 2]:
        if not isinstance(item, dict):
            continue
        authority, reason = check_authority(item)
        label = _text(item.get("case_name") or item.get("citation") or "unnamed authority", 200)
        if authority is None:
            result.rejected.append(Rejected(label, reason))
        elif _citation_key(authority.citation) in seen:
            result.rejected.append(Rejected(label, "duplicate citation"))
        elif len(result.authorities) >= MAX_AUTHORITIES:
            result.rejected.append(Rejected(label, f"more than {MAX_AUTHORITIES} authorities"))
        else:
            seen.add(_citation_key(authority.citation))
            result.authorities.append(authority)
    for item in (data.get("statutes") or [])[:10]:
        if isinstance(item, dict) and _text(item.get("name")) and _text(item.get("provision")):
            result.statutes.append({k: _text(item.get(k), 300) for k in ("name", "provision", "relevance")})
    if result.status == "ok" and not result.authorities:
        result.status = "no_results"
        if result.rejected:
            result.note = (result.note + " " if result.note else "") + "Every authority Lex returned failed the citation checks."
    if result.status in ("site_error", "no_results") and hit_rate_limit(result):
        result.status = "rate_limited"
    return result


def hit_rate_limit(result: SearchResult) -> bool:
    """Did NWLR show its security check during this search, whatever Lex managed to verify before it?"""
    return bool(_RATE_LIMIT_WORDS.search(result.note or ""))


STATUS_MESSAGES = {
    "no_results": "I couldn't find an authority on point in NWLR Online.",
    "login_failed": "I couldn't sign in to NWLR Online, so no search ran. The firm's login may need updating.",
    "site_error": "NWLR Online or the research assistant had a problem, so this search didn't finish.",
    "rate_limited": "NWLR Online is limiting searches from GrootOps right now, so this search didn't finish. Try again in about 2 hours.",
}


def format_for_chat(question: str, result: SearchResult) -> str:
    """Plain text with light markdown, for WhatsApp or Telegram."""
    if result.status != "ok":
        lines = [STATUS_MESSAGES.get(result.status, STATUS_MESSAGES["site_error"])]
        if result.note:
            lines.append(result.note)
        return "\n\n".join(lines)
    lines = [result.answer or f"Authorities on: {question}", ""]
    for number, a in enumerate(result.authorities, 1):
        lines.append(f"{number}. **{a.case_name}** {a.citation}" + (f", {a.court}" if a.court else ""))
        if a.holding:
            lines.append(f"   {a.holding}")
        lines.append(f"> {a.quote}" + (f" ({a.page})" if a.page else ""))
        lines.append(f"   [Open the report]({a.source_url})")
        lines.append("")
    if result.statutes:
        lines.append("**Statutes:** " + "; ".join(f"{s['name']}, {s['provision']}" for s in result.statutes))
    if result.note:
        lines.append(f"**Note:** {result.note}")
    lines.append("_Research aid only: check each authority before you rely on it._")
    return "\n".join(lines).strip()


def format_markdown(question: str, result: SearchResult) -> str:
    """A fuller report for evaluation runs: everything kept, everything rejected and why."""
    out = [f"## {question}", "", f"**Status:** {result.status}", ""]
    if result.answer:
        out += [result.answer, ""]
    if result.authorities:
        out += ["| # | Case | Citation | Court | Holding |", "| --- | --- | --- | --- | --- |"]
        for n, a in enumerate(result.authorities, 1):
            cell = lambda s: s.replace("|", "\\|")
            out.append(f"| {n} | [{cell(a.case_name)}]({a.source_url}) | {cell(a.citation)} | {cell(a.court)} | {cell(a.holding)} |")
        out.append("")
    if result.statutes:
        out += ["**Statutes:** " + "; ".join(f"{s['name']}, {s['provision']}" for s in result.statutes), ""]
    if result.rejected:
        out += ["**Rejected by the citation checks:**"] + [f"- {r.label}: {r.reason}" for r in result.rejected] + [""]
    if result.searches_run:
        out += ["**Searches Lex ran:** " + "; ".join(result.searches_run), ""]
    if result.note:
        out += [f"**Note:** {result.note}", ""]
    return "\n".join(out)


class CaseSearch:
    """Sends one question to Lex and returns a verified SearchResult. One search at a time per bot."""

    def __init__(self, api_base: str, bot_id: str, call: Callable = http_json, chat: OpsChat | None = None,
                 timeout: float = SEARCH_TIMEOUT):
        self.api_base, self.bot_id, self._call = api_base.rstrip("/"), bot_id, call
        self._chat = chat or OpsChat(api_base, bot_id, call=call)
        self.timeout = timeout
        # Lex researches in one chat, so searches queue rather than interleave.
        self._lock = threading.Lock()

    def search(self, question: str, on_wait: Callable[[], None] = lambda: None, known: list[dict] = ()) -> SearchResult:
        request = build_request(question, known)
        with self._lock:
            return self._search(request, on_wait)

    def answer(self, question: str, on_wait: Callable[[], None] = lambda: None) -> str:
        """The ready-to-send text for a chat channel."""
        return format_for_chat(question, self.search(question, on_wait))

    def _search(self, request: str, on_wait: Callable[[], None]) -> SearchResult:
        # Each question starts with a clean context so one matter's research never leaks into the next.
        status, _ = self._call(f"{self.api_base}/api/bots/{self.bot_id}/start-fresh", {})
        if status >= 300:
            log.warning("start-fresh answered %s; continuing in the existing context", status)
        held: list[dict] = []

        def on_card(card: dict) -> str | None:
            # Lex runs at full access, so a card here means a sign-in or credential prompt: a person must look.
            held.append(card)
            return None

        reply = self._chat.ask(request, on_wait=on_wait, on_card=on_card, timeout=self.timeout)
        if held:
            title = _text(held[0].get("title") or "a question", 120)
            return SearchResult(status="login_failed", note=f"Lex stopped to ask: {title}. Answer it in the GrootOps web app.")
        if reply is None:
            return SearchResult(status="site_error", note="The search took longer than expected. Check Lex's chat in the GrootOps web app.")
        data, problem = parse_reply(reply)
        if data is None and _SIGN_IN_WORDS.search(reply):
            return SearchResult(status="login_failed", note="Lex could not sign in to NWLR Online with the saved login.")
        return verify(data, problem)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def preflight(api_base: str, bot_id: str, call: Callable = http_json) -> list[Check]:
    """Is everything ready for a live search? Reads settings only; never reads a saved password."""
    api_base = api_base.rstrip("/")
    checks: list[Check] = []
    status, health = call(f"{api_base}/api/health")
    checks.append(Check("OpenMausBot server", status == 200, health.get("version", f"answered {status}")))
    if status != 200:
        return checks
    status, config = call(f"{api_base}/api/config")
    engine = (config.get("browserEngine") or {}) if status == 200 else {}
    checks.append(Check("Browser engine installed", engine.get("kind") not in (None, "unavailable"),
                        engine.get("reason") or engine.get("kind") or f"config answered {status}"))
    status, bot = call(f"{api_base}/api/bots/{bot_id}")
    bot = (bot.get("bot") or bot) if status == 200 else {}
    checks.append(Check("Lex bot exists", bool(bot.get("id")), bot.get("name") or f"answered {status}"))
    if bot.get("id"):
        checks.append(Check("Lex has a browser", bot.get("browser") is True and bot.get("computer") == "browser",
                            f"computer={bot.get('computer')}, browser={bot.get('browser')}"))
        checks.append(Check("Lex is at full access", bot.get("approvalMode") == "full", f"approvalMode={bot.get('approvalMode')}"))
    status, logins = call(f"{api_base}/api/logins")
    granted = [
        login for login in (logins.get("logins") or [])
        if NWLR_HOST in str(login.get("site") or login.get("host") or "").lower()
        and (login.get("bots") == "all" or bot_id in (login.get("bots") or []))
    ]
    checks.append(Check("NWLR Online login saved for Lex", bool(granted),
                        "saved" if granted else "not saved yet: run scripts/legal/save_nwlr_login.sh"))
    return checks
