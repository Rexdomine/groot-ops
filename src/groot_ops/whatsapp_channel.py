"""WhatsApp Cloud API channel for the lead bridge.

Meta calls GET /whatsapp/webhook once to verify the address, then POSTs signed message events to it.
Each text message is answered on a background thread (Meta wants a fast 200), one message at a time
per contact, so Ada's thread never gets two turns at once. Status events (sent, delivered, read) are
ignored. Configuration is re-read from its JSON file on every request, so credentials can be filled
in or a 24-hour test token replaced without restarting the service.

Config file keys: verify_token, app_secret, access_token, phone_number_id, graph_version (optional).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import threading
from collections import OrderedDict
from typing import Callable, Iterator

log = logging.getLogger("groot_ops.whatsapp_channel")

DEFAULT_GRAPH_VERSION = "v25.0"
MAX_REPLY_CHARS = 4096
SEEN_LIMIT = 2000
NON_TEXT_REPLY = "Thanks! I can only read text messages for now. Please type your question and I'll help right away."
FALLBACK_REPLY = "Thanks for your message! An agent will get back to you shortly."


def extract_messages(payload: dict, phone_number_id: str) -> Iterator[tuple[dict, str]]:
    """Yield (message, sender profile name) for inbound messages addressed to our number."""
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            if str((value.get("metadata") or {}).get("phone_number_id", "")) != str(phone_number_id):
                continue
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name", "") for c in value.get("contacts") or []}
            for message in value.get("messages") or []:
                if message.get("id") and message.get("from"):
                    yield message, names.get(message["from"], "")


def describe_event(payload: dict, phone_number_id: str) -> str:
    """One log line about an event's shape, never its content."""
    parts = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            pnid = str((value.get("metadata") or {}).get("phone_number_id", ""))
            parts.append(
                f"field={change.get('field')} ours={pnid == str(phone_number_id)} "
                f"messages={[m.get('type') for m in value.get('messages') or []]} "
                f"statuses={[(s.get('status'), [(e.get('code'), e.get('title')) for e in s.get('errors') or []]) for s in value.get('statuses') or []]} "
                f"errors={[e.get('code') for e in value.get('errors') or []]}"
            )
    return f"object={payload.get('object')} " + ("; ".join(parts) or "no changes")


def message_text(message: dict) -> str | None:
    kind = message.get("type")
    if kind == "text":
        return (message.get("text") or {}).get("body")
    if kind == "button":
        return (message.get("button") or {}).get("text")
    if kind == "interactive":
        interactive = message.get("interactive") or {}
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return reply.get("title")
    return None


class WhatsAppChannel:
    def __init__(
        self,
        config: Callable[[], dict],
        handle: Callable[[str, str, str, str], dict],
        post: Callable,
        run: Callable[[Callable[[], None]], None] | None = None,
    ):
        self.config, self.handle, self._post = config, handle, post
        self._run = run or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._seen_lock = threading.Lock()
        self._contact_locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()

    # --- Meta's address check -------------------------------------------------------------------
    def verify(self, query: dict[str, str]) -> tuple[int, str]:
        expected = str(self.config().get("verify_token") or "")
        given = query.get("hub.verify_token", "")
        if expected and query.get("hub.mode") == "subscribe" and hmac.compare_digest(given, expected):
            return 200, query.get("hub.challenge", "")
        return 403, "forbidden"

    # --- Inbound events -------------------------------------------------------------------------
    def receive(self, raw: bytes, signature: str) -> int:
        cfg = self.config()
        secret = str(cfg.get("app_secret") or "")
        if not secret or not cfg.get("phone_number_id"):
            return 503
        expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature or ""):
            return 401
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return 400
        log.info("WhatsApp event: %s", describe_event(payload, cfg["phone_number_id"]))
        for message, profile in extract_messages(payload, cfg["phone_number_id"]):
            if self._first_time(message["id"]):
                self._run(lambda m=message, p=profile: self._process(m, p))
        return 200

    def _first_time(self, message_id: str) -> bool:
        with self._seen_lock:
            if message_id in self._seen:
                return False
            self._seen[message_id] = None
            while len(self._seen) > SEEN_LIMIT:
                self._seen.popitem(last=False)
            return True

    def _lock_for(self, contact: str) -> threading.Lock:
        with self._locks_lock:
            return self._contact_locks.setdefault(contact, threading.Lock())

    def _process(self, message: dict, profile: str) -> None:
        wa_id = re.sub(r"\D", "", message["from"])
        contact = "+" + wa_id
        with self._lock_for(contact):
            self._mark_read(message["id"])
            text = message_text(message)
            if not text:
                reply = NON_TEXT_REPLY
            else:
                try:
                    reply = self.handle("whatsapp", contact, text, profile).get("reply") or FALLBACK_REPLY
                except Exception:  # never leave a lead without an answer
                    log.exception("bridge failed for a WhatsApp message")
                    reply = FALLBACK_REPLY
            self.send_text(wa_id, reply)

    # --- Outbound -------------------------------------------------------------------------------
    def _messages_url(self, cfg: dict) -> str:
        version = cfg.get("graph_version") or DEFAULT_GRAPH_VERSION
        return f"https://graph.facebook.com/{version}/{cfg['phone_number_id']}/messages"

    def _call(self, body: dict) -> tuple[int, dict]:
        cfg = self.config()
        headers = {"Authorization": f"Bearer {cfg.get('access_token', '')}"}
        return self._post(self._messages_url(cfg), body, headers, timeout=30)

    def send_text(self, wa_id: str, text: str) -> bool:
        status, data = self._call({
            "messaging_product": "whatsapp", "recipient_type": "individual", "to": wa_id,
            "type": "text", "text": {"preview_url": False, "body": text[:MAX_REPLY_CHARS]},
        })
        if status >= 300:
            log.warning("WhatsApp send failed (%s): %s", status, (data.get("error") or {}).get("message", data))
        return status < 300

    def _mark_read(self, message_id: str) -> None:
        """Blue ticks plus a typing indicator while Ada thinks; falls back to plain read receipts."""
        body = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
        status, _ = self._call({**body, "typing_indicator": {"type": "text"}})
        if status >= 300:
            self._call(body)
