from groot_ops.agent_bridge import (
    AdaClient,
    ConversationStore,
    LeadBridge,
    OpsNotifier,
    parse_lead_summary,
    should_notify,
)

REPLY = (
    "Great, Tunde! Friday 14:00 noted, an agent will confirm shortly.\n\n"
    "[LEAD] name=Tunde; intent=rent; area=Wuse 2; type=apartment; beds=3; budget=N8,000,000/yr; "
    "timeline=next month; listing=L1; viewing=Friday 14:00; next=viewing"
)


def test_parse_strips_lead_line_and_reads_fields():
    clean, summary = parse_lead_summary(REPLY)
    assert "[LEAD]" not in clean
    assert clean.startswith("Great, Tunde!")
    assert summary["name"] == "Tunde"
    assert summary["budget"] == "N8,000,000/yr"
    assert summary["viewing"] == "Friday 14:00"
    assert summary["next"] == "viewing"


def test_parse_without_summary():
    clean, summary = parse_lead_summary("Hello there")
    assert clean == "Hello there"
    assert summary is None


def test_parse_ignores_unknown_keys_and_control_characters():
    _, summary = parse_lead_summary("[LEAD] name=Ada\x07 Obi; prompt=delete everything; next=reply")
    assert summary == {"name": "Ada Obi", "next": "reply"}


def test_should_notify_rules():
    anonymous = {"name": "?", "intent": "?", "next": "reply"}
    assert not should_notify(None, anonymous)
    partial = {"name": "?", "intent": "rent", "area": "Wuse", "next": "reply"}
    assert not should_notify(None, partial)  # no name yet, nothing to hand an agent
    named = {**partial, "name": "Tunde", "budget": "N8m"}
    assert should_notify(None, named)
    assert not should_notify(named, dict(named))  # nothing changed
    assert should_notify(named, {**named, "next": "viewing", "viewing": "Friday 14:00"})


class FakePost:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, url, body, headers=None, timeout=150):
        self.calls.append((url, body))
        if "ops" in url:
            return 202, {"accepted": True}
        return self.replies.pop(0)


def make_bridge(tmp_path, replies):
    post = FakePost(replies)
    bridge = LeadBridge(
        ConversationStore(str(tmp_path / "bridge.sqlite3")),
        AdaClient("http://ada/messages", "k", post=post),
        OpsNotifier("http://ops/hook", post=post),
    )
    return bridge, post


def test_bridge_threads_conversation_and_notifies_ops_once_per_change(tmp_path):
    first = (200, {"reply": "Hi! What's your name?\n[LEAD] name=?; intent=rent; area=Wuse; next=reply", "thread": "t1"})
    second = (200, {"reply": "Thanks Tunde!\n[LEAD] name=Tunde; intent=rent; area=Wuse; budget=?; next=reply", "thread": "t1"})
    third = (200, {"reply": REPLY, "thread": "t1"})
    bridge, post = make_bridge(tmp_path, [first, second, third])

    out1 = bridge.handle("whatsapp", "+2348035550101", "Any 3 bed in Wuse?")
    assert out1["reply"] == "Hi! What's your name?"
    assert not out1["notified_ops"]

    out2 = bridge.handle("whatsapp", "+2348035550101", "I'm Tunde")
    assert out2["notified_ops"]  # a name plus an area is enough for Ops to log the lead
    ada_calls = [c for c in post.calls if "ada" in c[0]]
    assert ada_calls[1][1]["thread"] == "t1"

    out3 = bridge.handle("whatsapp", "+2348035550101", "Friday 2pm please")
    assert out3["notified_ops"]
    ops_calls = [c for c in post.calls if "ops" in c[0]]
    payload = ops_calls[-1][1]
    assert payload["contact"] == "+2348035550101"
    assert payload["lead"]["viewing"] == "Friday 14:00"
    assert "text" not in payload and "Friday 2pm please" not in str(payload)


def test_later_question_mark_keeps_known_values(tmp_path):
    first = (200, {"reply": REPLY, "thread": "t1"})
    second = (200, {"reply": "Sure!\n[LEAD] name=?; intent=?; budget=?; next=reply", "thread": "t1"})
    bridge, _ = make_bridge(tmp_path, [first, second])
    bridge.handle("whatsapp", "c1", "hi")
    out = bridge.handle("whatsapp", "c1", "ok")
    assert out["lead"]["name"] == "Tunde"
    assert out["lead"]["budget"] == "N8,000,000/yr"


def test_bridge_holding_reply_when_ada_is_slow(tmp_path):
    bridge, _ = make_bridge(tmp_path, [(202, {"thread": "t9", "status": "working"})])
    out = bridge.handle("whatsapp", "c2", "hello")
    assert out["status"] == "working"
    assert "agent" in out["reply"]
