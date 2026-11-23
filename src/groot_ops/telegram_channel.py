"""Telegram channel: the agent's private line to Ops, the back-office assistant.

The bridge long-polls Telegram (no public address needed) and passes each message from a paired chat
to Ops through the local OpenMausBot API, in Ops's main chat, so the web app shows the same thread.
Ops runs with its own tools (Gmail, Sheets, Docs, Drive, Slides) and approval rules.

Only paired chats are served. A chat pairs by sending `/start <pair code>` once; the code lives in the
config file next to the bot token. Paired chat IDs are kept in a separate, writable state file.

Config file keys: bot_token, pair_code. State file: {"allowed": [chat ids]}.
"""
from __future__ import annotations

import hmac
import html
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

log = logging.getLogger("groot_ops.telegram_channel")

API = "https://api.telegram.org/bot{token}/{method}"
MAX_CHARS = 4000
OPS_TIMEOUT = 15 * 60
FRAMING = (
    "[Telegram, from the agent you work for. Your final message is shown on a phone, so make it easy to scan: "
    "open with one line saying what happened, then short '- ' bullets with **bold** labels "
    "(e.g. '- **Viewing:** Sat 11am'), and named links like [Leads sheet](url) instead of raw URLs. "
    "No tables, no headings, no long paragraphs. Put any message the agent should send a client in "
    "lines starting with '> ' so it shows as a quote they can copy. "
    "If this is a forwarded client message: add or update the lead in the Leads sheet, then give that "
    "ready-to-send reply.]\n\n"
)
WELCOME = (
    "Hi! I'm your GrootOps back-office assistant.\n\n"
    "Forward me a client's WhatsApp message and I'll log the lead and draft your reply. "
    "Or just ask: book a viewing, write a listing description, make a property deck, "
    "draft an email, or tell you what's in the pipeline."
)
NOT_PAIRED = "This is a private GrootOps assistant. Send /start followed by your pairing code to connect."
NON_TEXT = "I can read text and captions for now. Please type or forward the message as text."
TIMEOUT_REPLY = "This is taking longer than expected. I'll keep working on it; check the GrootOps web app for the result."
CARD_UNANSWERED = "No answer came for the approval, so Ops is still waiting. You can answer it in the GrootOps web app."
CARD_WAIT = 30 * 60
FAILED_REPLY ="Sorry, something went wrong reaching the back office. Please try again in a minute."


def http_json(url: str, body: dict | None = None, timeout: float = 70) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read() or b"{}")
        except json.JSONDecodeError:
            return error.code, {}


def message_to_text(message: dict) -> str | None:
    """Text for Ops, labelling forwarded messages with who originally sent them."""
    text = message.get("text") or message.get("caption")
    if not text:
        return None
    origin = message.get("forward_origin")
    if not origin:
        return text
    user = origin.get("sender_user") or {}
    who = (" ".join(filter(None, [user.get("first_name"), user.get("last_name")]))
           or origin.get("sender_user_name") or (origin.get("chat") or {}).get("title") or "a client")
    return f"Forwarded message from {who}:\n{text}"


def _inline(text: str) -> str:
    """Markdown inline marks to Telegram HTML. Code and links are set aside first so nothing inside them changes."""
    held: list[str] = []

    def hold(fragment: str) -> str:
        held.append(fragment)
        return f"\x00{len(held) - 1}\x00"

    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`\n]+)`", lambda m: hold(f"<code>{m.group(1)}</code>"), text)
    text = re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)",
                  lambda m: hold(f'<a href="{m.group(2).replace(chr(34), "%22")}">{m.group(1)}</a>'), text)
    text = re.sub(r"https?://[^\s<>\x00]+", lambda m: hold(m.group(0)), text)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])", r"<i>\1</i>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: held[int(m.group(1))], text)


def markdown_to_telegram(text: str) -> str:
    """Ops writes Markdown; Telegram shows a small HTML subset. Bullets, headings, quotes and tables become phone-friendly."""
    out: list[str] = []
    quote: list[str] = []
    in_code, code = False, []

    def flush_quote() -> None:
        if quote:
            out.append("<blockquote>" + "\n".join(quote) + "</blockquote>")
            quote.clear()

    for line in text.split("\n"):
        if line.strip().startswith("```"):
            if in_code:
                out.append("<pre>" + html.escape("\n".join(code), quote=False) + "</pre>")
                code = []
            else:
                flush_quote()
            in_code = not in_code
            continue
        if in_code:
            code.append(line)
            continue
        stripped = line.strip()
        if stripped.startswith(">"):
            quote.append(_inline(stripped.lstrip(">").strip()))
            continue
        flush_quote()
        if re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?", stripped):
            continue  # table separator row
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            out.append(_inline(" · ".join(c for c in cells if c)))
            continue
        heading = re.match(r"#{1,6}\s+(.*)", stripped)
        if heading:
            out.append("<b>" + _inline(heading.group(1).strip("*_ ")) + "</b>")
            continue
        if re.fullmatch(r"[-*_]{3,}", stripped):
            out.append("")
            continue
        bullet = re.match(r"(\s*)[-*+]\s+(.*)", line)
        if bullet:
            indent = "    " if len(bullet.group(1).expandtabs()) >= 2 else ""
            out.append(f"{indent}{'◦' if indent else '•'} {_inline(bullet.group(2))}")
            continue
        out.append(_inline(line))
    if in_code:
        out.append("<pre>" + html.escape("\n".join(code), quote=False) + "</pre>")
    flush_quote()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def split_text(text: str, limit: int = MAX_CHARS) -> list[str]:
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        cut = cut if cut > limit // 2 else limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks + ([text] if text else [])


def pending_cards(messages: list[dict], since: int, handled: set[str]) -> list[dict]:
    """Approval or question cards Ops raised after our message that nobody has answered yet."""
    cards = []
    for m in messages:
        card = m.get("card") or {}
        if (m.get("kind") == "options" and card.get("requestId") and card.get("options")
                and int(m.get("at") or 0) >= since and card["requestId"] not in handled
                and not card.get("answered") and not card.get("resolved")):
            cards.append(card)
    return cards


def respond_body(card: dict, choice: str) -> dict:
    """Approval cards take allow/deny (the server reads any other behavior as deny); questions take an answer."""
    body = {"requestId": card["requestId"]}
    if [o.lower() for o in card.get("options") or []] == ["allow", "deny"]:
        return {**body, "behavior": "allow" if choice.lower() == "allow" else "deny",
                **({"message": "Denied by the user."} if choice.lower() != "allow" else {})}
    return {**body, "behavior": "answer", "message": choice}


CARD_FIELDS = (("recipient_email", "To"), ("to", "To"), ("cc", "Cc"), ("subject", "Subject"),
               ("title", "Title"), ("name", "Name"))


def card_text(card: dict) -> str:
    """Telegram HTML for an approval card: the action, then who and what, never a raw HTML email body."""
    esc = lambda s: html.escape(str(s), quote=False)
    title = card.get("title") or "Ops needs your answer"
    lines = [f"🔔 <b>{esc(title)}</b>"]
    subtitle = str(card.get("subtitle") or "")
    head, _, rest = subtitle.partition("\n")
    try:
        args = json.loads(rest) if rest.strip().startswith("{") else None
    except json.JSONDecodeError:
        args = None
    if args is None:
        found = {k: m.group(1) for k, _ in CARD_FIELDS
                 if (m := re.search(rf'"{k}"\s*:\s*"((?:[^"\\]|\\.)*)"', rest))}
        args = found or None
    if head:
        lines.append(esc(head))
    if isinstance(args, dict):
        shown = set()
        for key, label in CARD_FIELDS:
            if args.get(key) and label not in shown:
                shown.add(label)
                lines.append(f"<b>{label}:</b> {esc(args[key])[:300]}")
    elif rest.strip():
        lines.append(esc(rest.strip())[:1500])
    if card.get("held"):
        lines.append(f"<i>{esc(card['held'])}</i>")
    return "\n".join(lines)[:3500]


class OpsChat:
    """Sends a message to an OpenMausBot bot's main chat and waits for that turn's reply."""

    def __init__(self, api_base: str, bot_id: str, call: Callable = http_json,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.api_base, self.bot_id = api_base.rstrip("/"), bot_id
        self._call, self._sleep, self._clock = call, sleep, clock

    def ask(self, text: str, on_wait: Callable[[], None] = lambda: None,
            on_card: Callable[[dict], str | None] = lambda card: None, timeout: float = OPS_TIMEOUT) -> str | None:
        status, bot = self._call(f"{self.api_base}/api/bots/{self.bot_id}")
        thread = (bot.get("bot") or bot).get("mainThreadId") if status < 300 else None
        if not thread:
            raise RuntimeError(f"Ops bot not found ({status})")
        status, sent = self._call(f"{self.api_base}/api/bots/{self.bot_id}/messages", {"threadId": thread, "text": text})
        request_id = (sent.get("message") or {}).get("id")
        sent_at = int((sent.get("message") or {}).get("at") or 0)
        if status >= 300 or not request_id:
            raise RuntimeError(f"Ops rejected the message ({status})")
        handled: set[str] = set()
        deadline = self._clock() + timeout
        while self._clock() < deadline:
            on_wait()
            self._sleep(4)
            _, page = self._call(f"{self.api_base}/api/threads/{thread}/messages")
            messages = page.get("messages") or []
            for card in pending_cards(messages, sent_at, handled):
                handled.add(card["requestId"])
                answer = on_card(card)
                if answer is None:
                    return CARD_UNANSWERED
                self._call(f"{self.api_base}/api/threads/{thread}/respond", respond_body(card, answer))
                deadline = self._clock() + timeout
            mine = [m for m in messages if m.get("requestMessageId") == request_id]
            if any(m.get("turnTerminal") or m.get("kind") == "digest" for m in mine):
                # Earlier texts are Ops narrating its steps; the last one is the answer.
                texts = [m.get("text", "") for m in mine if m.get("role") == "bot" and m.get("kind") == "text"]
                texts = [t.strip() for t in texts if t and t.strip()]
                return texts[-1] if texts else None
        return None


class TelegramChannel:
    def __init__(self, config: Callable[[], dict], state_path: str, ops: OpsChat,
                 call: Callable = http_json, run: Callable[[Callable[[], None]], None] | None = None):
        self.config, self.state_path, self.ops, self._call = config, state_path, ops, call
        self._run = run or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self._chat_locks: dict[int, threading.Lock] = {}
        self._lock = threading.Lock()
        self._offset = 0
        self._cards: dict[str, tuple[int, list[str], threading.Event, list[str], str]] = {}
        self.card_wait = CARD_WAIT

    # --- Telegram API ---------------------------------------------------------------------------
    def _api(self, method: str, body: dict, timeout: float = 70) -> tuple[int, dict]:
        token = str(self.config().get("bot_token") or "")
        return self._call(API.format(token=token, method=method), body, timeout=timeout)

    def send(self, chat_id: int, text: str) -> None:
        """Send Markdown as Telegram HTML; if Telegram rejects the markup, resend that part as plain text."""
        for chunk in split_text(text, limit=3500):
            base = {"chat_id": chat_id, "link_preview_options": {"is_disabled": True}}
            status, data = self._api("sendMessage", {**base, "text": markdown_to_telegram(chunk), "parse_mode": "HTML"})
            if status >= 300:
                log.warning("Telegram rejected formatting (%s): %s", status, data.get("description"))
                status, data = self._api("sendMessage", {**base, "text": chunk})
            if status >= 300:
                log.warning("Telegram send failed (%s): %s", status, data.get("description"))

    def typing(self, chat_id: int) -> None:
        self._api("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=10)

    # --- Pairing --------------------------------------------------------------------------------
    def allowed(self) -> set[int]:
        try:
            with open(self.state_path, encoding="utf-8") as handle:
                return {int(c) for c in json.load(handle).get("allowed", [])}
        except (OSError, ValueError):
            return set()

    def _allow(self, chat_id: int) -> None:
        chats = sorted(self.allowed() | {chat_id})
        tmp = self.state_path + ".tmp"
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as handle:
            json.dump({"allowed": chats}, handle)
        os.replace(tmp, self.state_path)

    # --- Updates --------------------------------------------------------------------------------
    def poll_once(self) -> None:
        status, data = self._api("getUpdates", {"offset": self._offset, "timeout": 50,
                                                "allowed_updates": ["message", "callback_query"]}, timeout=70)
        if status >= 300:
            log.warning("Telegram getUpdates failed (%s): %s", status, data.get("description"))
            time.sleep(10)
            return
        for update in data.get("result") or []:
            self._offset = max(self._offset, int(update["update_id"]) + 1)
            if update.get("message"):
                self.on_message(update["message"])
            elif update.get("callback_query"):
                self.on_button(update["callback_query"])

    # --- Approval cards -------------------------------------------------------------------------
    def ask_card(self, chat_id: int, card: dict) -> str | None:
        """Show Ops's approval or question card as buttons and wait for the agent's tap."""
        token, options = secrets.token_hex(4), [str(o) for o in card["options"]][:8]
        event, answer = threading.Event(), []
        text = card_text(card)
        self._cards[token] = (chat_id, options, event, answer, text)
        buttons = [[{"text": o[:60], "callback_data": f"card:{token}:{i}"}] for i, o in enumerate(options)]
        self._api("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                  "link_preview_options": {"is_disabled": True},
                                  "reply_markup": {"inline_keyboard": buttons}})
        log.info("Telegram approval card shown: %s", card.get("tool") or "question")
        event.wait(self.card_wait)
        self._cards.pop(token, None)
        return answer[0] if answer else None

    def on_button(self, query: dict) -> None:
        self._api("answerCallbackQuery", {"callback_query_id": query.get("id")}, timeout=10)
        message = query.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        parts = str(query.get("data") or "").split(":")
        if len(parts) != 3 or parts[0] != "card" or chat_id not in self.allowed():
            return
        entry = self._cards.get(parts[1])
        if not entry or entry[0] != chat_id or not parts[2].isdigit() or int(parts[2]) >= len(entry[1]):
            self._api("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message.get("message_id"),
                                                 "reply_markup": {"inline_keyboard": []}}, timeout=10)
            return
        _, options, event, answer, text = entry
        choice = options[int(parts[2])]
        answer.append(choice)
        event.set()
        log.info("Telegram approval answered")
        self._api("editMessageText", {"chat_id": chat_id, "message_id": message.get("message_id"),
                                      "text": text + f"\n\n{'✅' if choice.lower() == 'allow' else '☑️'} <b>You chose: {html.escape(choice, quote=False)}</b>",
                                      "parse_mode": "HTML",
                                      "link_preview_options": {"is_disabled": True}}, timeout=10)

    def on_message(self, message: dict) -> None:
        chat = message.get("chat") or {}
        chat_id, text = chat.get("id"), (message.get("text") or "").strip()
        if chat_id is None or chat.get("type") != "private":
            return
        log.info("Telegram message: paired=%s command=%s", chat_id in self.allowed(), text.split(" ")[0][:12] if text.startswith("/") else "-")
        if text.startswith("/start"):
            code = text[len("/start"):].strip()
            expected = str(self.config().get("pair_code") or "")
            if chat_id in self.allowed():
                self.send(chat_id, WELCOME)
            elif expected and hmac.compare_digest(code, expected):
                self._allow(chat_id)
                log.info("Telegram chat paired")
                self.send(chat_id, "Connected. " + WELCOME)
            else:
                self.send(chat_id, NOT_PAIRED)
            return
        if chat_id not in self.allowed():
            self.send(chat_id, NOT_PAIRED)
            return
        body = message_to_text(message)
        if not body:
            self.send(chat_id, NON_TEXT)
            return
        self._run(lambda: self._process(chat_id, body))

    def _process(self, chat_id: int, body: str) -> None:
        with self._lock:
            lock = self._chat_locks.setdefault(chat_id, threading.Lock())
        with lock:
            try:
                reply = self.ops.ask(FRAMING + body, on_wait=lambda: self.typing(chat_id),
                                     on_card=lambda card: self.ask_card(chat_id, card))
            except Exception:
                log.exception("Ops request failed")
                reply = FAILED_REPLY
            self.send(chat_id, reply or TIMEOUT_REPLY)

    def serve_forever(self) -> None:
        log.info("Telegram channel polling")
        while True:
            try:
                self.poll_once()
            except Exception:
                log.exception("Telegram poll failed")
                time.sleep(10)
