import hashlib
import hmac
import json

from groot_ops.whatsapp_channel import NON_TEXT_REPLY, WhatsAppChannel

CONFIG = {
    "verify_token": "verify-me",
    "app_secret": "shh",
    "access_token": "token",
    "phone_number_id": "111",
}


def sign(raw: bytes, secret: str = "shh") -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def event(message: dict, phone_number_id: str = "111") -> bytes:
    return json.dumps({
        "object": "whatsapp_business_account",
        "entry": [{"id": "waba", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "15550000000", "phone_number_id": phone_number_id},
            "contacts": [{"profile": {"name": "Tunde"}, "wa_id": "2348035550101"}],
            "messages": [message],
        }}]}],
    }).encode()


TEXT = {"from": "2348035550101", "id": "wamid.1", "type": "text", "text": {"body": "Any 3 bed in Wuse?"}}


class Recorder:
    def __init__(self, config=CONFIG):
        self.handled, self.posts = [], []
        self.channel = WhatsAppChannel(
            config=lambda: config,
            handle=self.handle,
            post=self.post,
            run=lambda fn: fn(),
        )

    def handle(self, channel, contact, text, profile):
        self.handled.append((channel, contact, text, profile))
        return {"reply": f"Ada: {text}"}

    def post(self, url, body, headers=None, timeout=30):
        self.posts.append((url, body, headers))
        return 200, {}

    def sent_texts(self):
        return [b for _, b, _ in self.posts if b.get("type") == "text"]


def test_verify_accepts_only_the_right_token():
    channel = Recorder().channel
    ok = {"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"}
    assert channel.verify(ok) == (200, "42")
    assert channel.verify({**ok, "hub.verify_token": "wrong"})[0] == 403


def test_rejects_bad_signature():
    rec = Recorder()
    raw = event(TEXT)
    assert rec.channel.receive(raw, sign(raw, "other")) == 401
    assert rec.handled == []


def test_text_message_goes_through_bridge_and_reply_is_sent():
    rec = Recorder()
    raw = event(TEXT)
    assert rec.channel.receive(raw, sign(raw)) == 200
    assert rec.handled == [("whatsapp", "+2348035550101", "Any 3 bed in Wuse?", "Tunde")]
    [sent] = rec.sent_texts()
    assert sent["to"] == "2348035550101"
    assert sent["text"]["body"] == "Ada: Any 3 bed in Wuse?"
    url, _, headers = rec.posts[-1]
    assert url.endswith("/111/messages")
    assert headers["Authorization"] == "Bearer token"


def test_duplicate_delivery_is_answered_once():
    rec = Recorder()
    raw = event(TEXT)
    rec.channel.receive(raw, sign(raw))
    rec.channel.receive(raw, sign(raw))
    assert len(rec.handled) == 1


def test_other_number_and_status_events_are_ignored():
    rec = Recorder()
    raw = event(TEXT, phone_number_id="999")
    assert rec.channel.receive(raw, sign(raw)) == 200
    status_only = json.dumps({"entry": [{"changes": [{"field": "messages", "value": {
        "metadata": {"phone_number_id": "111"}, "statuses": [{"id": "wamid.1", "status": "read"}]}}]}]}).encode()
    assert rec.channel.receive(status_only, sign(status_only)) == 200
    assert rec.handled == [] and rec.posts == []


def test_non_text_message_gets_polite_reply_without_bridge():
    rec = Recorder()
    raw = event({"from": "2348035550101", "id": "wamid.2", "type": "audio", "audio": {"id": "a1"}})
    rec.channel.receive(raw, sign(raw))
    assert rec.handled == []
    assert rec.sent_texts()[0]["text"]["body"] == NON_TEXT_REPLY


def test_not_configured_yet():
    rec = Recorder(config={"verify_token": "verify-me"})
    raw = event(TEXT)
    assert rec.channel.receive(raw, sign(raw)) == 503
