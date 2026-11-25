from groot_ops.case_search import KNOWN_HEADER, build_request, verify
from groot_ops.legal.nwlr import HOUR, PageBudget, ResultCache, count_pages, waiting_note, words
from groot_ops.legal.runner import SearchRunner
from groot_ops.legal.store import LegalStore

CASE = {"case_name": "Adekoya v. F.H.A.", "citation": "(2008) 11 NWLR (Pt. 1099) 539", "court": "Supreme Court",
        "year": 2008, "holding": "A contractual cause of action accrues on breach, not on signing.",
        "quote": "a cause of action arises when there is a breach of the agreement", "page": "543",
        "source_url": "https://nwlronline.com/dashboard/legal-research/MTA5OV8xXzUzOQ=="}
GOOD = {"status": "ok", "answer": "Time runs from breach.", "authorities": [CASE]}
LIMITATION = "When does time begin to run under the statute of limitations for an action founded on simple contract?"


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


class FakeSearch:
    def __init__(self, data=GOOD):
        self.data, self.calls = data, []

    def search(self, question, on_wait=lambda: None, known=()):
        self.calls.append((question, list(known)))
        return verify(self.data)


class FakeWatcher:
    def __init__(self, pages):
        self.actions = ["mcp__browser__agent_browser_open {\"url\": \"https://nwlronline.com/dashboard/x\"}"] * pages

    def poll(self, since_ms):
        return [], self.actions


def setup(tmp_path, data=GOOD, pages=5, **budget):
    store, clock = LegalStore(str(tmp_path / "l.sqlite3")), Clock()
    user = store.add_user("ada@firm.ng", "Ada", "correct-horse-1")
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock.now += seconds

    search = FakeSearch(data)
    runner = SearchRunner(store, search, FakeWatcher(pages), clock=clock, budget=PageBudget(store, clock, **budget),
                          cache=ResultCache(store, clock), sleep=sleep)
    return store, user, runner, search, clock, sleeps


def ask(store, user, runner, question):
    sid = store.new_search(user, question)["id"]
    runner.run(sid)
    return store.search(user, sid)


def test_counts_only_nwlr_page_opens():
    assert count_pages(["mcp__browser__agent_browser_open {\"url\": \"https://nwlronline.com/a\"}",
                        "mcp__browser__agent_browser_eval {\"script\": \"nwlronline.com\"}",
                        "mcp__browser__agent_browser_open {\"url\": \"https://example.com\"}"]) == 1


def test_a_search_waits_until_the_hours_pages_leave_room(tmp_path):
    store, user, runner, search, clock, sleeps = setup(tmp_path, pages_per_hour=10, pages_per_search=8)
    store.record_pages(5, clock.now - HOUR + 600)   # these leave the hour in 10 minutes
    done = ask(store, user, runner, "pre-action notice government agency")
    assert done["status"] == "done" and sum(sleeps) >= 600
    assert len(store.page_times(clock.now - HOUR)) == 5          # the old 5 left, Lex's 5 counted


def test_an_nwlr_block_pauses_searches_for_the_cooldown(tmp_path):
    store, user, runner, search, clock, sleeps = setup(
        tmp_path, data={"status": "site_error", "authorities": [], "note": "NWLR rate limit"})
    assert ask(store, user, runner, "first question about service")["result"]["status"] == "rate_limited"
    ask(store, user, runner, "second question about jurisdiction")
    assert sum(sleeps) >= HOUR - 1


def test_waiting_searches_tell_the_lawyer_when_they_start(tmp_path):
    store, user, runner, search, clock, _ = setup(tmp_path)
    notes = []
    runner.sleep = lambda s: (notes.append(store.search(user, sid)["narration"]), setattr(clock, "now", clock.now + s))
    store.set_state("blocked_until", clock.now + 150)
    sid = store.new_search(user, "banker customer jurisdiction")["id"]
    runner.run(sid)
    assert notes[0] == waiting_note(150) and "3 min" in notes[0]


def test_the_same_question_is_answered_from_the_verified_result(tmp_path):
    store, user, runner, search, clock, _ = setup(tmp_path)
    ask(store, user, runner, LIMITATION)
    pages = len(store.page_times(clock.now - HOUR))
    again = ask(store, user, runner, "  when does time begin to run under the statute of limitations for an action founded on simple contract")
    assert len(search.calls) == 1
    assert again["result"]["authorities"][0]["citation"] == CASE["citation"]
    assert again["result"]["note"].startswith("Reused from a verified search")
    assert len(store.page_times(clock.now - HOUR)) == pages        # no NWLR pages for a reuse


def test_a_similar_question_hands_lex_the_known_authorities(tmp_path):
    store, user, runner, search, clock, _ = setup(tmp_path)
    ask(store, user, runner, LIMITATION)
    ask(store, user, runner, "From when is limitation computed for breach of a simple contract?")
    assert search.calls[1][1][0]["citation"] == CASE["citation"]
    ask(store, user, runner, "Is a pre-action notice a condition precedent to suing a government agency?")
    assert search.calls[2][1] == []                                 # unrelated: nothing offered


def test_failed_searches_are_not_cached(tmp_path):
    store, user, runner, search, clock, _ = setup(tmp_path, data={"status": "no_results", "authorities": []})
    ask(store, user, runner, LIMITATION)
    ask(store, user, runner, LIMITATION)
    assert len(search.calls) == 2


def test_known_authorities_go_into_the_request_compactly():
    request = build_request("limitation simple contract", [CASE])
    assert KNOWN_HEADER.strip() in request and CASE["source_url"] in request
    assert build_request("limitation simple contract") == build_request("limitation simple contract", [])
    assert "contract" in words("Contracts") and "the" not in words("the court")


def test_a_block_mentioned_alongside_verified_results_still_pauses_searches(tmp_path):
    data = {**GOOD, "note": "Two verified; NWLR then showed a security check."}
    store, user, runner, search, clock, sleeps = setup(tmp_path, data=data)
    assert ask(store, user, runner, "first question about service")["result"]["status"] == "ok"
    ask(store, user, runner, "second question about jurisdiction")
    assert sum(sleeps) >= HOUR
