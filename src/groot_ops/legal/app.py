"""GrootOps Legal web app: a chat-style Case Search for lawyers, served from the VPS next to Lex.

    LEGAL_DB=/var/lib/grootops-legal/legal.sqlite3 \
    LEGAL_CASE_SEARCH_FILE=/etc/grootops-bridge/case-search.json \
    uvicorn --factory groot_ops.legal.app:create_app --host 127.0.0.1 --port 8820

LEGAL_PREVIEW=1 runs with sample results instead of Lex, clearly labelled, for local design checks.
LEGAL_SECURE_COOKIES=1 marks the session cookie Secure (set it behind HTTPS).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from groot_ops.case_search import CaseSearch, SearchResult, preflight, verify
from groot_ops.legal.memo import build_memo
from groot_ops.legal.nwlr import PageBudget, ResultCache
from groot_ops.legal.runner import COURTS, STEPS, LexWatcher, SearchRunner
from groot_ops.legal.store import ACTIVE, LegalStore

STATIC = Path(__file__).parent / "static"
COOKIE = "grootops_legal"
MAX_QUESTION = 1500
LOGIN_FAILURES, LOGIN_WINDOW = 5, 15 * 60
STATUS_TTL = 60
# What lawyers see in the court picker (runner.COURTS holds the phrasing Lex is given).
COURT_LABELS = {"": "All courts", "supreme": "Supreme Court", "appeal": "Court of Appeal", "high": "High Courts"}


class PreviewSearch:
    """Sample results for design checks only. Every authority is labelled as a sample."""

    def search(self, question, on_wait=lambda: None, known=()):
        for _ in range(3):
            time.sleep(1.2)
            on_wait()
        sample = {
            "status": "ok",
            "answer": "Preview mode: these are sample results to show the layout, not real research.",
            "authorities": [
                {"case_name": "Sample Appellant v. Example Respondent", "citation": "(2019) 4 NWLR (Pt. 1662) 242",
                 "court": "Supreme Court", "year": 2019, "holding": "Sample holding: one sentence on what the court decided.",
                 "quote": "Sample passage. In live mode this is the exact text from the judgment Lex read.", "page": "p. 260",
                 "source_url": "https://nwlronline.com/sample-case-page"},
                {"case_name": "Placeholder Ltd v. Demonstration Bank Plc", "citation": "(2021) LPELR-55555(CA)",
                 "court": "Court of Appeal", "year": 2021, "holding": "Sample holding for a second authority.",
                 "quote": "Another sample passage, shown in the gold quote bar.", "page": "",
                 "source_url": "https://nwlronline.com/sample-case-page-2"},
                {"case_name": "Bogus citation example", "citation": "not a real citation", "quote": "x",
                 "source_url": "https://nwlronline.com/x"},
            ],
            "statutes": [{"name": "Sample Statute", "provision": "Section 1", "relevance": "Sample."}],
            "searches_run": ["sample search one", "sample search two"],
            "note": "",
        }
        return verify(sample)


class PreviewWatcher:
    def __init__(self):
        self.calls = 0

    def texts_since(self, since_ms):
        self.calls += 1
        return [["Signing in with the saved login.", "Running the searches now.", "Opening the top cases to read the holdings."][min(self.calls - 1, 2)]]


def create_app() -> FastAPI:
    preview = os.environ.get("LEGAL_PREVIEW") == "1"
    store = LegalStore(os.environ.get("LEGAL_DB", "legal.sqlite3"))
    cfg: dict = {}
    if not preview:
        with open(os.environ.get("LEGAL_CASE_SEARCH_FILE", "/etc/grootops-bridge/case-search.json"), encoding="utf-8") as handle:
            cfg = json.load(handle)
        runner = SearchRunner(store, CaseSearch(cfg["api_base"], cfg["bot_id"]), LexWatcher(cfg["api_base"], cfg["bot_id"]),
                              budget=PageBudget(store, time.time), cache=ResultCache(store, time.time))
    else:
        runner = SearchRunner(store, PreviewSearch(), PreviewWatcher())
    runner.start()
    secure = os.environ.get("LEGAL_SECURE_COOKIES") == "1"
    failures: dict[str, deque] = defaultdict(deque)
    status_cache = {"at": 0.0, "value": None}
    status_lock = threading.Lock()

    app = FastAPI(title="GrootOps Legal", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Writes must come from our own page: a custom header can't be sent cross-site without CORS.
        if request.method in ("POST", "DELETE", "PUT") and request.headers.get("x-requested-with") != "grootops-legal":
            return JSONResponse({"error": "Refused."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    def current_user(request: Request) -> dict:
        user = store.user_for(request.cookies.get(COOKIE))
        if user is None:
            raise HTTPException(401, "Sign in to continue.")
        return user

    def public_search(search: dict) -> dict:
        ahead = runner.queued_ahead() if search["status"] == "queued" else 0
        return {k: search[k] for k in ("id", "thread_id", "question", "court", "status", "step", "narration",
                                       "result", "feedback", "created_at", "finished_at")} | {"queued_ahead": ahead}

    # --- pages --------------------------------------------------------------------------------
    @app.get("/")
    def index(request: Request):
        if store.user_for(request.cookies.get(COOKIE)) is None:
            return RedirectResponse("/login", status_code=303)
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/login")
    def login_page():
        return FileResponse(STATIC / "login.html", headers={"Cache-Control": "no-store"})

    @app.get("/static/{name}")
    def static(name: str):
        path = STATIC / name
        if not re.fullmatch(r"[\w.-]+\.(css|js|svg|png)", name) or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    @app.get("/health")
    def health():
        return {"ok": True, "preview": preview}

    # --- auth ---------------------------------------------------------------------------------
    @app.post("/api/login")
    async def login(request: Request, response: Response):
        body = await request.json()
        email, password = str(body.get("email") or "").strip().lower(), str(body.get("password") or "")
        recent = failures[email]
        while recent and recent[0] < time.time() - LOGIN_WINDOW:
            recent.popleft()
        if len(recent) >= LOGIN_FAILURES:
            raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
        token = store.login(email, password)
        if token is None:
            recent.append(time.time())
            raise HTTPException(401, "That email and password don't match.")
        recent.clear()
        response.set_cookie(COOKIE, token, httponly=True, secure=secure, samesite="lax", max_age=14 * 24 * 3600)
        return {"ok": True}

    @app.post("/api/logout")
    def logout(request: Request, response: Response):
        store.logout(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/me")
    def me(user: dict = Depends(current_user)):
        return {"name": user["name"], "email": user["email"], "firm": user["firm"], "preview": preview,
                "steps": STEPS, "courts": [{"value": k, "label": COURT_LABELS[k]} for k in COURTS]}

    @app.get("/api/status")
    def status(user: dict = Depends(current_user)):
        if preview:
            return {"nwlr": "preview", "detail": "Preview mode: sample results"}
        with status_lock:
            if status_cache["value"] is None or time.time() - status_cache["at"] > STATUS_TTL:
                try:
                    checks = preflight(cfg["api_base"], cfg["bot_id"])
                    missing = [c.name for c in checks if not c.ok]
                    status_cache["value"] = {"nwlr": "connected" if not missing else "not_ready", "detail": ", ".join(missing)}
                except OSError:
                    status_cache["value"] = {"nwlr": "offline", "detail": "The research assistant can't be reached."}
                status_cache["at"] = time.time()
            return status_cache["value"]

    # --- threads and searches -----------------------------------------------------------------
    @app.get("/api/threads")
    def threads(user: dict = Depends(current_user)):
        return {"threads": store.threads(user["id"])}

    @app.get("/api/threads/{thread_id}")
    def thread(thread_id: str, user: dict = Depends(current_user)):
        found = store.thread(user["id"], thread_id)
        if found is None:
            raise HTTPException(404, "That search isn't in your history.")
        return {**found, "searches": [public_search(s) for s in found["searches"]]}

    @app.delete("/api/threads/{thread_id}")
    def delete_thread(thread_id: str, user: dict = Depends(current_user)):
        if not store.delete_thread(user["id"], thread_id):
            raise HTTPException(404)
        return {"ok": True}

    @app.post("/api/searches")
    async def new_search(request: Request, user: dict = Depends(current_user)):
        body = await request.json()
        question = " ".join(str(body.get("question") or "").split())
        court = str(body.get("court") or "")
        thread_id = body.get("thread_id") or None
        if not question:
            raise HTTPException(400, "Type a research question first.")
        if len(question) > MAX_QUESTION:
            raise HTTPException(400, f"Keep the question under {MAX_QUESTION} characters.")
        if court not in COURTS:
            raise HTTPException(400, "Pick a court from the list.")
        if thread_id:
            current = store.thread(user["id"], thread_id)
            if current is None:
                raise HTTPException(404, "That search isn't in your history.")
            if any(s["status"] in ACTIVE for s in current["searches"]):
                raise HTTPException(409, "Wait for the current search in this chat to finish.")
        created = store.new_search(user["id"], question, court, thread_id)
        runner.submit(created["id"])
        return public_search(store.search(user["id"], created["id"]))

    @app.get("/api/searches/{search_id}")
    def get_search(search_id: str, user: dict = Depends(current_user)):
        found = store.search(user["id"], search_id)
        if found is None:
            raise HTTPException(404)
        return public_search(found)

    @app.post("/api/searches/{search_id}/feedback")
    async def feedback(search_id: str, request: Request, user: dict = Depends(current_user)):
        value = str((await request.json()).get("feedback") or "")
        if value not in ("up", "down", ""):
            raise HTTPException(400)
        if not store.set_feedback(user["id"], search_id, value):
            raise HTTPException(404)
        return {"ok": True}

    # --- saved authorities --------------------------------------------------------------------
    @app.get("/api/saved")
    def saved(user: dict = Depends(current_user)):
        return {"saved": store.saved(user["id"])}

    @app.post("/api/saved")
    async def save(request: Request, user: dict = Depends(current_user)):
        body = await request.json()
        search = store.search(user["id"], str(body.get("search_id") or ""))
        citation = str(body.get("citation") or "")
        match = next((a for a in ((search or {}).get("result") or {}).get("authorities") or [] if a["citation"] == citation), None)
        if match is None:
            raise HTTPException(404, "That authority isn't in your results.")
        if body.get("saved") is False:
            store.unsave_authority(user["id"], citation)
        else:
            store.save_authority(user["id"], search["id"], match)
        return {"ok": True}

    # --- memo ---------------------------------------------------------------------------------
    @app.get("/api/threads/{thread_id}/memo.docx")
    def memo(thread_id: str, user: dict = Depends(current_user)):
        found = store.thread(user["id"], thread_id)
        if found is None:
            raise HTTPException(404)
        done = [s for s in found["searches"] if s["status"] == "done"]
        if not done:
            raise HTTPException(409, "There are no finished searches to export yet.")
        data = build_memo(found["title"], user["name"], user["firm"], done)
        name = re.sub(r"[^\w]+", "-", found["title"]).strip("-")[:60] or "research"
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": f'attachment; filename="memo-{name}.docx"'})

    return app
