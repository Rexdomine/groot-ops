import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from groot_ops.case_search import verify
from groot_ops.legal import app as legal_app
from groot_ops.legal.memo import build_memo
from groot_ops.legal.runner import SearchRunner, compose_question, step_from
from groot_ops.legal.store import LegalStore

H = {"X-Requested-With": "grootops-legal"}
GOOD = {
    "status": "ok", "answer": "Service otherwise than ordered is void.",
    "authorities": [{"case_name": "Mark v. Eke", "citation": "(2004) 5 NWLR (Pt. 865) 54", "court": "Supreme Court",
                     "year": 2004, "holding": "Void.", "quote": "Any other mode is a nullity.", "page": "p. 79",
                     "source_url": "https://nwlronline.com/case/1"}],
}


class InstantSearch:
    def __init__(self, data=GOOD):
        self.data, self.asked = data, []

    def search(self, question, on_wait=lambda: None, known=()):
        self.asked.append(question)
        on_wait()
        return verify(self.data)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LEGAL_PREVIEW", "1")
    monkeypatch.setenv("LEGAL_DB", str(tmp_path / "legal.sqlite3"))
    LegalStore(str(tmp_path / "legal.sqlite3")).add_user("ada@firm.ng", "Ada Obi", "correct-horse-1", "Pilot Chambers")
    # Run searches inline with a fake Lex instead of the preview worker's sample delays.
    fake = InstantSearch()
    monkeypatch.setattr(legal_app, "PreviewSearch", lambda: fake)
    monkeypatch.setattr(SearchRunner, "start", lambda self: None)
    monkeypatch.setattr(SearchRunner, "submit", lambda self, sid: self.run(sid))
    c = TestClient(legal_app.create_app())
    c.fake = fake
    return c


def sign_in(client, password="correct-horse-1"):
    return client.post("/api/login", json={"email": "ADA@firm.ng ", "password": password}, headers=H)


def test_pages_need_a_session(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    assert client.get("/api/threads").status_code == 401
    assert sign_in(client, "wrong-password").status_code == 401
    assert sign_in(client).status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/api/me").json()["name"] == "Ada Obi"


def test_writes_without_the_app_header_are_refused(client):
    sign_in(client)
    assert client.post("/api/searches", json={"question": "x"}).status_code == 403


def test_login_attempts_are_limited(client):
    for _ in range(5):
        sign_in(client, "nope-nope-nope")
    assert sign_in(client).status_code == 429


def test_search_runs_and_lands_in_history_with_a_follow_up_carrying_context(client):
    sign_in(client)
    first = client.post("/api/searches", json={"question": "  service   contrary to order ", "court": "supreme"}, headers=H).json()
    assert first["question"] == "service contrary to order"
    thread = client.get(f"/api/threads/{first['thread_id']}").json()
    done = thread["searches"][0]
    assert done["status"] == "done" and done["result"]["authorities"][0]["citation"] == "(2004) 5 NWLR (Pt. 865) 54"
    assert client.fake.asked[0] == "service contrary to order Only cite authorities from the Supreme Court."
    client.post("/api/searches", json={"question": "what about substituted service?", "thread_id": first["thread_id"]}, headers=H)
    assert client.fake.asked[1].startswith("Earlier question in this matter: service contrary to order. Follow-up:")
    assert [t["title"] for t in client.get("/api/threads").json()["threads"]] == ["service contrary to order"]


def test_bad_input_is_refused_with_plain_messages(client):
    sign_in(client)
    assert client.post("/api/searches", json={"question": " "}, headers=H).json()["detail"] == "Type a research question first."
    assert client.post("/api/searches", json={"question": "q", "court": "moon"}, headers=H).status_code == 400
    assert client.post("/api/searches", json={"question": "q", "thread_id": "not-mine"}, headers=H).status_code == 404


def test_lawyers_only_see_their_own_history(client, tmp_path):
    sign_in(client)
    mine = client.post("/api/searches", json={"question": "mine"}, headers=H).json()
    LegalStore(str(tmp_path / "legal.sqlite3")).add_user("bola@firm.ng", "Bola", "another-pass-1")
    client.post("/api/logout", headers=H)
    client.post("/api/login", json={"email": "bola@firm.ng", "password": "another-pass-1"}, headers=H)
    assert client.get("/api/threads").json()["threads"] == []
    assert client.get(f"/api/threads/{mine['thread_id']}").status_code == 404
    assert client.get(f"/api/searches/{mine['id']}").status_code == 404


def test_save_feedback_and_memo(client):
    sign_in(client)
    s = client.post("/api/searches", json={"question": "service"}, headers=H).json()
    assert client.post("/api/saved", json={"search_id": s["id"], "citation": "(2004) 5 NWLR (Pt. 865) 54"}, headers=H).status_code == 200
    assert client.post("/api/saved", json={"search_id": s["id"], "citation": "made up"}, headers=H).status_code == 404
    assert client.get("/api/saved").json()["saved"][0]["case_name"] == "Mark v. Eke"
    assert client.post(f"/api/searches/{s['id']}/feedback", json={"feedback": "up"}, headers=H).status_code == 200
    memo = client.get(f"/api/threads/{s['thread_id']}/memo.docx")
    assert memo.status_code == 200 and "memo-service.docx" in memo.headers["content-disposition"]
    document = zipfile.ZipFile(io.BytesIO(memo.content)).read("word/document.xml").decode()
    assert "Mark v. Eke" in document and "Any other mode is a nullity." in document


def test_memo_escapes_text_and_links():
    data = build_memo("A & B <test>", "Ada", "", [{"question": "q", "status": "done", "result": {
        "status": "ok", "answer": "x", "authorities": [{**GOOD["authorities"][0], "source_url": "https://nwlronline.com/a?b=1&c=2"}]}}])
    z = zipfile.ZipFile(io.BytesIO(data))
    assert "A &amp; B &lt;test&gt;" in z.read("word/document.xml").decode()
    assert "b=1&amp;c=2" in z.read("word/_rels/document.xml.rels").decode()


def test_progress_only_moves_forward():
    assert step_from([], 0) == 0
    assert step_from(["Signing in now"], 0) == 0
    assert step_from(["Running the searches now"], 0) == 1
    assert step_from(["Running the searches", "Opening the top cases"], 0) == 2
    assert step_from(["Signing in"], 2) == 2


def test_progress_follows_lex_browser_actions_when_it_works_silently():
    from groot_ops.legal.runner import describe
    search = 'mcp__browser__agent_browser_open {"url": "https://nwlronline.com/dashboard/legal-research?search_term=service%20contrary%20to%20order"}'
    case = 'mcp__browser__agent_browser_open {"url": "https://nwlronline.com/dashboard/legal-research/MTU3N18xXzQxMA%3D%3D"}'
    read = 'mcp__browser__agent_browser_eval {"script": "(async()=>{const K=[\'service\']"}'
    assert step_from([], 0, [search]) == 1
    assert step_from([], 0, [search, case, read]) == 2
    assert step_from([], 2, [search]) == 2
    assert describe([search]) == "Searching: service contrary to order"
    assert describe([search, case, read, case, read]) == "Reading report 2"
    assert describe([]) == ""


def test_compose_question():
    assert compose_question("q") == "q"
    assert compose_question("q", "appeal", "earlier") == "Earlier question in this matter: earlier. Follow-up: q Only cite authorities from the Court of Appeal."


def test_a_restart_marks_unfinished_searches_failed(tmp_path):
    path = str(tmp_path / "x.sqlite3")
    store = LegalStore(path)
    uid = store.add_user("a@b.ng", "A", "long-enough-pw")
    created = store.new_search(uid, "q")
    assert store.search(uid, created["id"])["status"] == "queued"
    assert LegalStore(path).search(uid, created["id"])["status"] == "failed"


def test_duplicate_accounts_and_short_passwords_are_refused(tmp_path):
    store = LegalStore(str(tmp_path / "x.sqlite3"))
    store.add_user("a@b.ng", "A", "long-enough-pw")
    with pytest.raises(ValueError):
        store.add_user("A@B.ng", "A", "long-enough-pw")
    with pytest.raises(ValueError):
        store.add_user("c@b.ng", "C", "short")
