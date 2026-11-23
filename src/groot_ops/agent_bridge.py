"""Lead bridge between a messaging channel, the lead-desk bot (Ada) and the back-office bot (Ops).

Flow for one inbound lead message:
    channel adapter -> POST /inbound -> Ada (OpenMausBot Bot API, confined, no tools)
    Ada's reply ends with a "[LEAD] key=value; ..." line. The bridge strips that line before
    the reply goes back to the lead, keeps the latest summary per contact, and when the summary
    changes in a way an agent cares about, posts the structured fields (never the lead's raw
    text) to Ops's webhook, where Ops updates Sheets, Docs and Gmail drafts.

Standard library only, so it runs on the VPS next to OpenMausBot without extra installs.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qsl, urlsplit

from groot_ops.telegram_channel import OpsChat, TelegramChannel
from groot_ops.whatsapp_channel import WhatsAppChannel

log = logging.getLogger("groot_ops.agent_bridge")

LEAD_FIELDS = ("name", "intent", "area", "type", "beds", "budget", "timeline", "listing", "viewing", "next")
# Fields whose change is worth waking Ops for. "next" moving to viewing/handoff always is.
NOTIFY_FIELDS = ("name", "intent", "area", "type", "beds", "budget", "timeline", "listing", "viewing", "next")
UNKNOWN = {"", "?", "none?", "unknown", "n/a"}
MAX_VALUE_LEN = 120
MAX_INBOUND_CHARS = 4000

_LEAD_LINE = re.compile(r"^\s*\[LEAD\](?P<body>.*)$", re.MULTILINE)


def parse_lead_summary(reply: str) -> tuple[str, dict[str, str] | None]:
    """Split Ada's reply into (text for the lead, summary fields). The last [LEAD] line wins."""
    matches = list(_LEAD_LINE.finditer(reply or ""))
    if not matches:
        return (reply or "").strip(), None
    summary: dict[str, str] = {}
    for part in matches[-1].group("body").split(";"):
        key, sep, value = part.partition("=")
        key = key.strip().lower()
        if sep and key in LEAD_FIELDS:
            summary[key] = clean_value(value)
    clean = _LEAD_LINE.sub("", reply).strip()
    return clean, summary


def clean_value(value: str) -> str:
    """One short line of plain text: lead-supplied words reach Ops only as data."""
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", value or "")
    value = re.sub(r"\s+", " ", value).strip().strip("`\"'")
    return value[:MAX_VALUE_LEN]


def known(value: str | None) -> bool:
    return bool(value) and value.strip().lower() not in UNKNOWN


def should_notify(previous: dict[str, str] | None, current: dict[str, str] | None) -> bool:
    """Wake Ops when the lead is identifiable and something an agent cares about changed."""
    if not current:
        return False
    if not (known(current.get("name")) or known(current.get("intent"))):
        return False
    previous = previous or {}
    changed = [f for f in NOTIFY_FIELDS if known(current.get(f)) and current.get(f) != previous.get(f)]
    if not changed:
        return False
    if current.get("next") in {"viewing", "handoff"} and "next" in changed:
        return True
    # Otherwise wait until there is enough to act on: a name plus what they want.
    return known(current.get("name")) and any(known(current.get(f)) for f in ("area", "budget", "listing"))


@dataclass
class Conversation:
    contact: str
    thread: str | None
    summary: dict[str, str] | None
    notified: dict[str, str] | None


class ConversationStore:
    """Per-contact Ada thread and lead summaries, in SQLite."""

    def __init__(self, path: str):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS conversations (contact TEXT PRIMARY KEY, channel TEXT, thread TEXT,"
            " summary TEXT, notified TEXT, updated_at TEXT)"
        )
        self._db.commit()

    def get(self, contact: str) -> Conversation:
        with self._lock:
            row = self._db.execute(
                "SELECT thread, summary, notified FROM conversations WHERE contact = ?", (contact,)
            ).fetchone()
        if not row:
            return Conversation(contact, None, None, None)
        return Conversation(contact, row[0], _loads(row[1]), _loads(row[2]))

    def save(self, contact: str, channel: str, thread: str | None, summary: dict | None, notified: dict | None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._db.execute(
                "INSERT INTO conversations (contact, channel, thread, summary, notified, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(contact) DO UPDATE SET channel = excluded.channel,"
                " thread = excluded.thread, summary = excluded.summary, notified = excluded.notified,"
                " updated_at = excluded.updated_at",
                (contact, channel, thread, _dumps(summary), _dumps(notified), now),
            )
            self._db.commit()


def _loads(text: str | None) -> dict | None:
    return json.loads(text) if text else None


def _dumps(value: dict | None) -> str | None:
    return json.dumps(value) if value is not None else None


def post_json(url: str, body: dict, headers: dict[str, str] | None = None, timeout: float = 150) -> tuple[int, dict]:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        raw = error.read() or b"{}"
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, {"error": raw[:300].decode(errors="replace")}


class AdaClient:
    """OpenMausBot Bot API: one confined conversation per contact."""

    def __init__(self, messages_url: str, key: str, post: Callable = post_json):
        self.messages_url, self._key, self._post = messages_url, key, post

    def ask(self, text: str, thread: str | None) -> tuple[str | None, str | None, str]:
        body = {"message": text, "wait": 120}
        if thread:
            body["thread"] = thread
        status, data = self._post(self.messages_url, body, {"Authorization": f"Bearer {self._key}"})
        if status == 404 and thread:
            # The thread is gone (deleted in the app): start a new one rather than fail the lead.
            return self.ask(text, None)
        if status == 200:
            return data.get("reply"), data.get("thread"), "ok"
        if status == 202:
            return None, data.get("thread"), data.get("status", "working")
        log.warning("Ada answered %s: %s", status, data.get("error"))
        return None, thread, "error"


class OpsNotifier:
    def __init__(self, webhook_url: str, post: Callable = post_json):
        self._url, self._post = webhook_url, post

    def notify(self, payload: dict) -> bool:
        status, data = self._post(self._url, payload, timeout=30)
        if status >= 300:
            log.warning("Ops webhook answered %s: %s", status, data)
        return status < 300


HOLDING_REPLY = "Thanks! Give me a moment, an agent will get back to you shortly."


class LeadBridge:
    def __init__(self, store: ConversationStore, ada: AdaClient, ops: OpsNotifier):
        self.store, self.ada, self.ops = store, ada, ops

    def handle(self, channel: str, contact: str, text: str, profile_name: str = "") -> dict:
        contact = clean_value(contact)
        text = (text or "").strip()[:MAX_INBOUND_CHARS]
        convo = self.store.get(contact)
        reply, thread, status = self.ada.ask(text, convo.thread)
        if reply is None:
            self.store.save(contact, channel, thread, convo.summary, convo.notified)
            return {"reply": HOLDING_REPLY, "status": status, "notified_ops": False}

        clean_reply, summary = parse_lead_summary(reply)
        if summary:
            # A later "?" never erases something the lead already told Ada.
            summary = {**(convo.summary or {}), **{k: v for k, v in summary.items() if known(v)}}
        else:
            summary = convo.summary
        notified = convo.notified
        sent = False
        if should_notify(convo.notified, summary):
            payload = {
                "event": "lead.updated",
                "channel": channel,
                "contact": contact,
                "profile_name": clean_value(profile_name),
                "lead": {f: summary.get(f, "?") for f in LEAD_FIELDS},
                "changed": [f for f in LEAD_FIELDS if summary.get(f) != (convo.notified or {}).get(f)],
                "at": datetime.now(timezone.utc).isoformat(),
            }
            sent = self.ops.notify(payload)
            if sent:
                notified = dict(summary)
        self.store.save(contact, channel, thread, summary, notified)
        return {"reply": clean_reply, "status": "ok", "lead": summary, "notified_ops": sent}


WHATSAPP_PATH = "/whatsapp/webhook"


def make_handler(bridge: LeadBridge, token: str, whatsapp: WhatsAppChannel | None = None):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 (http.server naming)
            if whatsapp and urlsplit(self.path).path == WHATSAPP_PATH:
                length = min(int(self.headers.get("Content-Length", "0") or 0), 256 * 1024)
                status = whatsapp.receive(self.rfile.read(length), self.headers.get("X-Hub-Signature-256", ""))
                return self._send(status, {"ok": status == 200})
            if self.path != "/inbound":
                return self._send(404, {"error": "not found"})
            if self.headers.get("Authorization", "") != f"Bearer {token}":
                return self._send(401, {"error": "unauthorized"})
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 64 * 1024)
                body = json.loads(self.rfile.read(length) or b"{}")
                contact, text = str(body["contact"]), str(body["text"])
            except (ValueError, KeyError, json.JSONDecodeError):
                return self._send(400, {"error": "send {contact, text, channel?, profile_name?}"})
            result = bridge.handle(str(body.get("channel", "test")), contact, text, str(body.get("profile_name", "")))
            self._send(200, result)

        def do_GET(self):  # noqa: N802
            url = urlsplit(self.path)
            if whatsapp and url.path == WHATSAPP_PATH:
                status, text = whatsapp.verify(dict(parse_qsl(url.query)))
                return self._send_text(status, text)
            self._send(200 if self.path == "/health" else 404, {"ok": self.path == "/health"})

        def _send_text(self, status: int, text: str):
            data = text.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send(self, status: int, body: dict):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            log.info("%s %s", self.address_string(), fmt % args)

    return Handler


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ada_file = _read_json(os.environ["BRIDGE_ADA_KEY_FILE"])
    ops_file = _read_json(os.environ["BRIDGE_OPS_WEBHOOK_FILE"])
    hooks_base = os.environ.get("BRIDGE_HOOKS_BASE", "http://127.0.0.1:8800")
    ada_url = re.sub(r"^https?://[^/]+", hooks_base, ada_file["url"])
    ops_url = re.sub(r"^https?://[^/]+", hooks_base, ops_file["credential"]["url"])
    with open(os.environ["BRIDGE_TOKEN_FILE"], encoding="utf-8") as handle:
        token = handle.read().strip()
    bridge = LeadBridge(
        ConversationStore(os.environ.get("BRIDGE_DB", "bridge.sqlite3")),
        AdaClient(ada_url, ada_file["key"]),
        OpsNotifier(ops_url),
    )
    whatsapp = None
    whatsapp_file = os.environ.get("BRIDGE_WHATSAPP_FILE")
    if whatsapp_file:
        whatsapp = WhatsAppChannel(config=lambda: _read_json(whatsapp_file), handle=bridge.handle, post=post_json)
        log.info("WhatsApp channel on %s", WHATSAPP_PATH)
    telegram_file = os.environ.get("BRIDGE_TELEGRAM_FILE")
    if telegram_file:
        ops_chat = OpsChat(os.environ.get("BRIDGE_OPS_API", "http://127.0.0.1:8799"), os.environ["BRIDGE_OPS_BOT_ID"])
        telegram = TelegramChannel(
            config=lambda: _read_json(telegram_file),
            state_path=os.environ.get("BRIDGE_TELEGRAM_STATE", "telegram-allowed.json"),
            ops=ops_chat,
        )
        threading.Thread(target=telegram.serve_forever, name="telegram", daemon=True).start()
    host, port = os.environ.get("BRIDGE_HOST", "127.0.0.1"), int(os.environ.get("BRIDGE_PORT", "8810"))
    log.info("lead bridge listening on http://%s:%s", host, port)
    ThreadingHTTPServer((host, port), make_handler(bridge, token, whatsapp)).serve_forever()


if __name__ == "__main__":
    main()
