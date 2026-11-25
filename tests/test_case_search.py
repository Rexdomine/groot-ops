import json

import pytest

from groot_ops.case_search import (
    CITATION_RE, CaseSearch, build_request, check_authority, check_source_url, format_for_chat, format_markdown, parse_reply,
    preflight, verify,
)
from groot_ops.telegram_channel import SEARCH_HELP, SEARCH_OFF, SEARCH_STARTED, TelegramChannel

CASE_URL = "https://nwlronline.com/dashboard/legal-research/case/12345"


def authority(**overrides):
    item = {
        "kind": "case", "case_name": "Mark v. Eke", "citation": "(2004) 5 NWLR (Pt. 865) 54", "court": "Supreme Court",
        "year": 2004, "holding": "Service in a manner other than that ordered is a nullity.",
        "quote": "Where the court has ordered a particular mode of service, any other mode is a nullity.",
        "page": "p. 79", "source_url": CASE_URL,
    }
    item.update(overrides)
    return item


def lex_reply(**data):
    body = {"status": "ok", "answer": "Service otherwise than ordered is void.", "authorities": [authority()],
            "statutes": [], "searches_run": ["service contrary to court order"], "note": ""}
    body.update(data)
    return "```json\n" + json.dumps(body) + "\n```"


def test_build_request_frames_the_question_and_refuses_empty_or_huge_ones():
    assert build_request("  grounds to set aside\n a writ ").endswith("Question: grounds to set aside a writ")
    with pytest.raises(ValueError):
        build_request("   ")
    with pytest.raises(ValueError):
        build_request("x" * 2001)


@pytest.mark.parametrize("citation", [
    "(2004) 5 NWLR (Pt. 865) 54", "(2019) 4 NWLR (Pt.1662) 242 at 260", "(2017) LPELR-42345(SC)",
    "(2010) All FWLR (Pt. 520) 1", "(2008) 5 SC (Pt. II) 1", "(1976) 6 SC 1", "(2012) 2 SCM 1",
])
def test_nigerian_law_report_citations_are_recognised(citation):
    assert CITATION_RE.match(citation)


@pytest.mark.parametrize("citation", ["", "Mark v Eke", "2004 NWLR 54", "(2004) Lagos Law Report 3", "see (2004) 5 NWLR (Pt. 865) 54"])
def test_malformed_citations_are_refused(citation):
    assert not CITATION_RE.match(citation)


@pytest.mark.parametrize("url, ok", [
    (CASE_URL, True),
    ("https://www.nwlronline.com/report/abc", True),
    ("http://nwlronline.com/report/abc", False),
    ("https://nwlronline.com/", False),
    ("https://nwlronline.com/dashboard/legal-research", False),
    ("https://nwlronline.com.evil.example/case/1", False),
    ("https://example.com/case/1", False),
    ("", False),
])
def test_source_must_be_a_case_page_on_nwlr_online(url, ok):
    assert (check_source_url(url) is None) is ok


def test_nwlr_links_must_open_the_cited_report():
    from groot_ops.case_search import link_mismatch
    base = "https://nwlronline.com/dashboard/legal-research/"
    assert link_mismatch("(1989) 3 NWLR (Pt. 109) 250", base + "MTA5XzFfMjUw") is None        # 109_1_250
    assert link_mismatch("(2009) 7 NWLR (Pt. 1139) 97", base + "MTEzOV8xXzk3") is None         # 1139_1_97
    assert "not the cited (Pt. 1689) 374" in link_mismatch("(2019) 13 NWLR (Pt. 1689) 374", base + "MTcxMF8xXzE=")
    assert link_mismatch("(2022) 11 NWLR (Pt. 1842) 405", base + "MTg0Ml8xXzQwNQ%3D%3D") is None  # URL-encoded padding
    assert "not the cited" in link_mismatch("(2022) 11 NWLR (Pt. 1842) 406", base + "MTg0Ml8xXzQwNQ%3D%3D")
    assert link_mismatch("(2017) LPELR-42345(SC)", base + "MTcxMF8xXzE=") is None              # not an NWLR cite
    assert link_mismatch("(2019) 4 NWLR (Pt. 1662) 242", base + "not-base64!") is None
    _, reason = check_authority(authority(citation="(2019) 13 NWLR (Pt. 1689) 374", year=2019, source_url=base + "MTcxMF8xXzE="))
    assert "link opens (Pt. 1710) 1" in reason


def test_square_bracket_years_are_accepted_and_shown_in_round_brackets():
    base = "https://nwlronline.com/dashboard/legal-research/"
    found, reason = check_authority(authority(citation="[2002] 9 NWLR (Pt. 773) 475", year=2002, source_url=base + "NzczXzFfNDc1"))
    assert found is not None, reason
    assert found.citation == "(2002) 9 NWLR (Pt. 773) 475"


def test_headnote_catchlines_are_not_accepted_as_quotes():
    _, reason = check_authority(authority(
        quote="Pre-action notice - When required for a suit against a public officer - Relevant considerations."))
    assert "headnote" in reason
    found, _ = check_authority(authority(quote="A pre-action notice is a condition precedent - a statutory one."))
    assert found is not None


def test_an_nwlr_security_check_is_reported_as_a_rate_limit():
    result = verify({"status": "site_error", "authorities": [], "note": "NWLR rate limit"})
    assert result.status == "rate_limited"
    assert "limiting searches" in format_for_chat("q", result)
    assert verify({"status": "site_error", "authorities": [], "note": "Page failed to load"}).status == "site_error"
    # Lex sometimes reports a block as no_results, or with its rejected leftovers: still a rate limit.
    assert verify({"status": "no_results", "authorities": [], "note": "NWLR hit a 429/security check"}).status == "rate_limited"


def test_parse_reply_takes_the_last_json_block_or_explains_why_not():
    data, problem = parse_reply("Working...\n" + lex_reply(answer="first") + "\n" + lex_reply(answer="second"))
    assert data["answer"] == "second" and problem == ""
    assert parse_reply('Done: {"status": "no_results"}')[0] == {"status": "no_results"}
    assert parse_reply("I could not do it.") == (None, "Lex's reply had no readable JSON block.")
    assert parse_reply(None)[0] is None


def test_verify_keeps_good_authorities_and_rejects_each_bad_one_with_a_reason():
    data = json.loads(lex_reply(authorities=[
        authority(),
        authority(case_name="Duplicate", citation="(2004)  5 NWLR (Pt 865) 54"),
        authority(case_name="Made up", citation="Made up v State"),
        authority(case_name="No quote", citation="(2010) 1 NWLR (Pt. 1175) 1", quote=""),
        authority(case_name="Search page", citation="(2011) 1 NWLR (Pt. 1228) 1", source_url="https://nwlronline.com/dashboard/legal-research"),
        authority(case_name="Wrong year", citation="(2012) 1 NWLR (Pt. 1280) 1", year=2015),
    ]).split("```json\n")[1].split("\n```")[0])
    result = verify(data)
    assert result.status == "ok"
    assert [a.citation for a in result.authorities] == ["(2004) 5 NWLR (Pt. 865) 54"]
    reasons = {r.label: r.reason for r in result.rejected}
    assert reasons["Duplicate"] == "duplicate citation"
    assert "law-report format" in reasons["Made up"]
    assert reasons["No quote"] == "no verbatim quote"
    assert "search or home page" in reasons["Search page"]
    assert "does not match" in reasons["Wrong year"]


def test_ok_with_nothing_surviving_the_checks_becomes_no_results():
    result = verify({"status": "ok", "authorities": [authority(citation="bogus")]})
    assert result.status == "no_results"
    assert "failed the citation checks" in result.note


def test_unknown_status_and_missing_data_are_site_errors():
    assert verify({"status": "weird"}).status == "site_error"
    assert verify(None, "Lex gave no reply.").note == "Lex gave no reply."


def test_chat_format_shows_citation_quote_and_link_and_a_caution():
    data, _ = parse_reply(lex_reply())
    text = format_for_chat("service", verify(data))
    assert "**Mark v. Eke** (2004) 5 NWLR (Pt. 865) 54, Supreme Court" in text
    assert "> Where the court has ordered" in text
    assert f"[Open the report]({CASE_URL})" in text
    assert "check each authority" in text
    assert "sign in" in format_for_chat("q", verify({"status": "login_failed"}))


def test_markdown_report_lists_rejections():
    data, _ = parse_reply(lex_reply(authorities=[authority(), authority(case_name="Bad", citation="nope")]))
    report = format_markdown("service", verify(data))
    assert "| 1 | [Mark v. Eke](" in report
    assert "- Bad: citation 'nope'" in report


class FakeChat:
    def __init__(self, reply=None, card=None):
        self.reply, self.card, self.asked = reply, card, []

    def ask(self, text, on_wait=lambda: None, on_card=lambda card: None, timeout=0):
        self.asked.append(text)
        on_wait()
        if self.card:
            return on_card(self.card)
        return self.reply


def fake_call(calls):
    def call(url, body=None, timeout=70):
        calls.append(url)
        return 200, {"ok": True}
    return call


def test_case_search_starts_fresh_then_returns_verified_results():
    calls = []
    chat = FakeChat(reply=lex_reply())
    result = CaseSearch("http://api", "lex", call=fake_call(calls), chat=chat).search("service on a defendant")
    assert calls == ["http://api/api/bots/lex/start-fresh"]
    assert chat.asked[0].endswith("Question: service on a defendant")
    assert result.status == "ok" and len(result.authorities) == 1


def test_a_card_from_lex_means_a_person_must_look():
    chat = FakeChat(card={"title": "Save a login for nwlronline.com?"})
    result = CaseSearch("http://api", "lex", call=fake_call([]), chat=chat).search("q")
    assert result.status == "login_failed"
    assert "Save a login" in result.note


def test_a_plain_text_sign_in_complaint_is_a_login_failure():
    reply = "There's no saved login for this site, so I've asked you to sign in there yourself."
    result = CaseSearch("http://api", "lex", call=fake_call([]), chat=FakeChat(reply=reply)).search("q")
    assert result.status == "login_failed"


def test_no_reply_in_time_is_a_site_error():
    result = CaseSearch("http://api", "lex", call=fake_call([]), chat=FakeChat(reply=None)).search("q")
    assert result.status == "site_error"


def test_preflight_reports_each_missing_piece_without_reading_passwords():
    seen = []

    def call(url, body=None, timeout=70):
        seen.append(url)
        if url.endswith("/api/health"):
            return 200, {"version": "0.1.169"}
        if url.endswith("/api/config"):
            return 200, {"browserEngine": {"kind": "engine"}}
        if url.endswith("/api/bots/lex"):
            return 200, {"id": "lex", "name": "Lex", "computer": "browser", "browser": True, "approvalMode": "full"}
        if url.endswith("/api/logins"):
            return 200, {"logins": [{"site": "nwlronline.com", "bots": ["someone-else"]}]}
        raise AssertionError(url)

    checks = {c.name: c.ok for c in preflight("http://api", "lex", call=call)}
    assert checks == {"OpenMausBot server": True, "Browser engine installed": True, "Lex bot exists": True,
                      "Lex has a browser": True, "Lex is at full access": True, "NWLR Online login saved for Lex": False}
    assert not any("password" in url for url in seen)


def make_channel(tmp_path, research):
    sent = []

    def call(url, body=None, timeout=70):
        if url.endswith("/sendMessage"):
            sent.append((body["chat_id"], body["text"]))
        return 200, {"ok": True, "result": []}

    channel = TelegramChannel(config=lambda: {"bot_token": "1:a", "pair_code": "code"},
                              state_path=str(tmp_path / "allowed.json"), ops=None, call=call,
                              run=lambda fn: fn(), research=research)
    channel._allow(7)
    return channel, sent


def test_telegram_search_command_runs_case_search(tmp_path):
    asked = []
    channel, sent = make_channel(tmp_path, lambda q, on_wait: asked.append(q) or "Found 2 authorities.")
    channel.on_message({"chat": {"id": 7, "type": "private"}, "text": "/search incompetent writ of summons"})
    assert asked == ["incompetent writ of summons"]
    assert [t for _, t in sent] == [SEARCH_STARTED, "Found 2 authorities."]


def test_telegram_search_without_a_question_or_when_off(tmp_path):
    channel, sent = make_channel(tmp_path, lambda q, w: "x")
    channel.on_message({"chat": {"id": 7, "type": "private"}, "text": "/search"})
    off, sent_off = make_channel(tmp_path, None)
    off.on_message({"chat": {"id": 7, "type": "private"}, "text": "/search anything"})
    assert sent[-1][1] == SEARCH_HELP and sent_off[-1][1] == SEARCH_OFF
