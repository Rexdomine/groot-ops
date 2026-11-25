import json

from groot_ops.telegram_channel import (
    FRAMING, NOT_PAIRED, OpsChat, TelegramChannel, message_to_text, split_text,
)


class FakeOps:
    def __init__(self, reply="Done."):
        self.reply, self.asked = reply, []

    def ask(self, text, on_wait=lambda: None, on_card=lambda card: None):
        on_wait()
        self.asked.append(text)
        return self.reply


def make_channel(tmp_path, ops=None):
    sent = []

    def call(url, body=None, timeout=70):
        method = url.rsplit("/", 1)[1]
        if method == "sendMessage":
            sent.append((body["chat_id"], body["text"]))
            assert body.get("parse_mode") == "HTML"
        return 200, {"ok": True, "result": []}

    channel = TelegramChannel(
        config=lambda: {"bot_token": "123:abc", "pair_code": "secret-code"},
        state_path=str(tmp_path / "allowed.json"),
        ops=ops or FakeOps(),
        call=call,
        run=lambda fn: fn(),
    )
    return channel, sent


def private(chat_id, text, **extra):
    return {"chat": {"id": chat_id, "type": "private"}, "text": text, **extra}


def test_unpaired_chats_are_refused_and_never_reach_ops(tmp_path):
    ops = FakeOps()
    channel, sent = make_channel(tmp_path, ops)
    channel.on_message(private(7, "show me the leads"))
    channel.on_message(private(7, "/start wrong-code"))
    assert sent == [(7, NOT_PAIRED), (7, NOT_PAIRED)]
    assert ops.asked == []


def test_pairing_then_messages_go_to_ops_with_framing(tmp_path):
    ops = FakeOps("Lead logged.")
    channel, sent = make_channel(tmp_path, ops)
    channel.on_message(private(7, "/start secret-code"))
    assert 7 in channel.allowed()
    assert json.loads((tmp_path / "allowed.json").read_text()) == {"allowed": [7]}
    channel.on_message(private(7, "Book a viewing for Tolu on Saturday"))
    assert ops.asked == [FRAMING + "Book a viewing for Tolu on Saturday"]
    assert sent[-1] == (7, "Lead logged.")


def test_group_chats_are_ignored(tmp_path):
    channel, sent = make_channel(tmp_path)
    channel.on_message({"chat": {"id": -5, "type": "group"}, "text": "/start secret-code"})
    assert sent == [] and channel.allowed() == set()


def test_forwarded_messages_name_the_original_sender():
    message = private(7, "Is the Lekki duplex still available?",
                      forward_origin={"type": "user", "sender_user": {"first_name": "Tolu", "last_name": "A"}})
    assert message_to_text(message) == "Forwarded message from Tolu A:\nIs the Lekki duplex still available?"
    hidden = private(7, "Hi", forward_origin={"type": "hidden_user", "sender_user_name": "Chika"})
    assert message_to_text(hidden).startswith("Forwarded message from Chika:")


def test_non_text_messages_get_a_hint(tmp_path):
    channel, sent = make_channel(tmp_path)
    channel.on_message(private(7, "/start secret-code"))
    channel.on_message({"chat": {"id": 7, "type": "private"}, "photo": [{}]})
    assert "text" in sent[-1][1]


def test_long_replies_are_split():
    parts = split_text(("line\n" * 2000), limit=4000)
    assert all(len(p) <= 4000 for p in parts) and len(parts) == 3


def test_ops_chat_waits_for_its_own_turn():
    pages = [
        {"messages": [{"requestMessageId": "other", "role": "bot", "kind": "text", "text": "old", "turnTerminal": True}]},
        {"messages": [
            {"requestMessageId": "m1", "role": "bot", "kind": "text", "text": "Working on it"},
            {"requestMessageId": "m1", "role": "bot", "kind": "text", "text": "Viewing booked.", "turnTerminal": True},
        ]},
    ]
    posted = []

    def call(url, body=None, timeout=70):
        if url.endswith("/api/bots/b1"):
            return 200, {"bot": {"mainThreadId": "t1"}}
        if url.endswith("/messages") and body is not None:
            posted.append(body)
            return 200, {"ok": True, "message": {"id": "m1"}}
        return 200, pages.pop(0)

    ops = OpsChat("http://local", "b1", call=call, sleep=lambda s: None)
    assert ops.ask("hello") == "Viewing booked."
    assert posted == [{"threadId": "t1", "text": "hello"}]


def test_approval_cards_become_buttons_and_the_tap_is_sent_to_ops(tmp_path):
    card = {"title": "Send on your behalf?", "subtitle": "Gmail - Send email", "options": ["Allow", "Deny"],
            "requestId": "r1", "tool": "GMAIL_SEND_EMAIL"}
    pages = [
        {"messages": [{"kind": "options", "at": 200, "card": card}]},
        {"messages": [{"requestMessageId": "m1", "role": "bot", "kind": "text", "text": "Email sent.", "turnTerminal": True}]},
    ]
    ops_calls = []

    def ops_call(url, body=None, timeout=70):
        if url.endswith("/api/bots/b1"):
            return 200, {"bot": {"mainThreadId": "t1"}}
        if body is not None:
            ops_calls.append((url.rsplit("/", 1)[1], body))
            return 200, {"ok": True, "message": {"id": "m1", "at": 100}}
        return 200, pages.pop(0)

    tg_calls = []
    channel = None

    def tg_call(url, body=None, timeout=70):
        method = url.rsplit("/", 1)[1]
        tg_calls.append((method, body))
        if method == "sendMessage" and "reply_markup" in body:
            data = body["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
            channel.on_button({"id": "q", "data": data, "message": {"chat": {"id": 7}, "message_id": 9, "text": body["text"]}})
        return 200, {"ok": True}

    ops = OpsChat("http://local", "b1", call=ops_call, sleep=lambda s: None)
    channel = TelegramChannel(config=lambda: {"bot_token": "1:a", "pair_code": "c"},
                              state_path=str(tmp_path / "allowed.json"), ops=ops, call=tg_call, run=lambda fn: fn())
    channel.on_message(private(7, "/start c"))
    channel.card_wait = 1
    channel.on_message(private(7, "Email me the brief"))
    assert ("respond", {"requestId": "r1", "behavior": "allow"}) in ops_calls
    assert any(m == "editMessageText" and "You chose: Allow" in b["text"] for m, b in tg_calls)
    assert tg_calls[-1][0] == "sendMessage" and tg_calls[-1][1]["text"] == "Email sent."
    assert tg_calls[-1][1]["parse_mode"] == "HTML"


def test_buttons_from_unpaired_chats_are_ignored(tmp_path):
    channel, sent = make_channel(tmp_path)
    channel.on_button({"id": "q", "data": "card:abcd:0", "message": {"chat": {"id": 99}, "message_id": 1}})
    assert sent == []


def test_question_cards_send_the_chosen_answer_and_deny_is_explicit():
    from groot_ops.telegram_channel import respond_body
    assert respond_body({"requestId": "r", "options": ["Allow", "Deny"]}, "Deny") == {
        "requestId": "r", "behavior": "deny", "message": "Denied by the user."}
    assert respond_body({"requestId": "q", "options": ["Lekki", "Ikoyi"]}, "Ikoyi") == {
        "requestId": "q", "behavior": "answer", "message": "Ikoyi"}


def test_markdown_becomes_readable_telegram_html():
    from groot_ops.telegram_channel import markdown_to_telegram
    md = """## Viewing booked

Tolu's viewing is set.

- **Viewing:** Sat 11am at 5 & 6 <Lekki>
- [Leads sheet](https://docs.google.com/spreadsheets/d/abc_def/edit)
  - phone_number still *missing*

| Field | Value |
|---|---|
| Budget | N4m |

> Hi Tolu, your viewing is confirmed for Saturday 11am.
> See you there!

Raw: https://docs.google.com/document/d/x_y_z/edit"""
    out = markdown_to_telegram(md)
    assert "<b>Viewing booked</b>" in out
    assert "• <b>Viewing:</b> Sat 11am at 5 &amp; 6 &lt;Lekki&gt;" in out
    assert '• <a href="https://docs.google.com/spreadsheets/d/abc_def/edit">Leads sheet</a>' in out
    assert "    ◦ phone_number still <i>missing</i>" in out
    assert "Budget · N4m" in out and "---" not in out
    assert "<blockquote>Hi Tolu, your viewing is confirmed for Saturday 11am.\nSee you there!</blockquote>" in out
    assert "https://docs.google.com/document/d/x_y_z/edit" in out and "<i>" not in out.split("Raw:")[1]


def test_rejected_markup_falls_back_to_plain_text(tmp_path):
    calls = []

    def call(url, body=None, timeout=70):
        calls.append(body)
        return (400, {"description": "can't parse entities"}) if body.get("parse_mode") else (200, {"ok": True})

    channel = TelegramChannel(config=lambda: {"bot_token": "1:a"}, state_path=str(tmp_path / "a.json"),
                              ops=FakeOps(), call=call, run=lambda fn: fn())
    channel.send(7, "**Done** <weird>")
    assert calls[-1] == {"chat_id": 7, "link_preview_options": {"is_disabled": True}, "text": "**Done** <weird>"}


def test_email_approval_cards_show_recipient_and_subject_not_the_html_body():
    from groot_ops.telegram_channel import card_text
    card = {"title": "Send on your behalf?", "held": "This sends something on your behalf, so it asks you first.",
            "subtitle": 'Gmail · Send email\n{"recipient_email":"agent@example.com","subject":"Viewing brief & notes",'
                        '"is_html":true,"body":"<!doctype html><html>...'}
    text = card_text(card)
    assert "<b>To:</b> agent@example.com" in text
    assert "<b>Subject:</b> Viewing brief &amp; notes" in text
    assert "doctype" not in text and "Gmail · Send email" in text
