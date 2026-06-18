from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from groot_ops import auth
from groot_ops.ui_app import create_app


class InMemoryAuthBackend:
    def __init__(self):
        self.users_by_email = {}
        self.sessions_by_hash = {}
        self.revoked_hashes = set()

    def create_user(self, *, email: str, password: str, full_name: str):
        email_normalized = auth.normalize_email(email)
        if email_normalized in self.users_by_email:
            raise auth.AuthError("An account with this email already exists.")
        user = auth.AuthUser(
            id="00000000-0000-0000-0000-%012d" % (len(self.users_by_email) + 1),
            email=email.strip(),
            full_name=full_name.strip(),
            role="user",
            status="active",
        )
        self.users_by_email[email_normalized] = {
            "user": user,
            "password_hash": auth.hash_password(password),
        }
        return user

    def authenticate_user(self, *, email: str, password: str, user_agent: str = "", ip_address: str = ""):
        record = self.users_by_email.get(auth.normalize_email(email))
        if not record or not auth.verify_password(password, record["password_hash"]):
            raise auth.AuthError("Invalid email or password.")
        token = auth.generate_session_token()
        self.sessions_by_hash[auth.hash_session_token(token)] = record["user"]
        return auth.AuthSession(user=record["user"], token=token, expires_at=datetime.now(timezone.utc))

    def get_user_for_session(self, token: str):
        token_hash = auth.hash_session_token(token)
        if token_hash in self.revoked_hashes:
            return None
        return self.sessions_by_hash.get(token_hash)

    def revoke_session(self, token: str) -> None:
        self.revoked_hashes.add(auth.hash_session_token(token))


class FailingAuthBackend(InMemoryAuthBackend):
    def create_user(self, *, email: str, password: str, full_name: str):
        raise auth.AuthError("Sign-up unavailable")


def test_password_hashing_is_salted_and_verifiable():
    first = auth.hash_password("correct horse battery staple")
    second = auth.hash_password("correct horse battery staple")

    assert first != second
    assert "correct horse" not in first
    assert auth.verify_password("correct horse battery staple", first) is True
    assert auth.verify_password("wrong password", first) is False


def test_ip_hash_uses_deployment_secret(monkeypatch):
    monkeypatch.setenv("GROOT_OPS_IP_HASH_SECRET", "first-secret")
    first = auth.hash_ip_address("203.0.113.10")

    monkeypatch.setenv("GROOT_OPS_IP_HASH_SECRET", "second-secret")
    second = auth.hash_ip_address("203.0.113.10")

    assert first != second
    assert auth.hash_ip_address("") == ""


def test_ip_hash_fails_closed_without_secret(monkeypatch):
    monkeypatch.delenv("GROOT_OPS_IP_HASH_SECRET", raising=False)
    monkeypatch.delenv("GROOT_OPS_SESSION_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="GROOT_OPS_IP_HASH_SECRET"):
        auth.hash_ip_address("203.0.113.10")

    assert auth.hash_ip_address("") == ""


def test_login_rate_limit_rejects_after_threshold():
    class FakeCursor:
        def __init__(self):
            self.query = ""
            self.params = None

        def execute(self, query, params):
            self.query = query
            self.params = params

        def fetchone(self):
            return (auth.LOGIN_RATE_LIMIT_MAX_FAILURES,)

    cursor = FakeCursor()
    backend = auth.DatabaseAuthBackend(connect=lambda: None)

    try:
        backend._raise_if_login_rate_limited(cursor, email_normalized="ada@example.com", ip_hash="ip-hash")
    except auth.AuthError as exc:
        assert "Too many failed login attempts" in str(exc)
    else:
        raise AssertionError("expected rate limit AuthError")
    assert "login_attempts" in cursor.query
    assert cursor.params == (auth.LOGIN_RATE_LIMIT_WINDOW_MINUTES, "ada@example.com", "ip-hash", "ip-hash")


def test_authenticate_user_checks_rate_limit_before_user_lookup(monkeypatch):
    monkeypatch.setenv("GROOT_OPS_IP_HASH_SECRET", "test-ip-secret")

    class FakeCursor:
        def __init__(self):
            self.calls = []
            self._next_row = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, query, params):
            self.calls.append((query, params))
            if "FROM login_attempts" in query:
                self._next_row = (auth.LOGIN_RATE_LIMIT_MAX_FAILURES,)

        def fetchone(self):
            return self._next_row

    class FakeConnection:
        def __init__(self):
            self.cursor_obj = FakeCursor()
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            self.committed = True

    connection = FakeConnection()
    backend = auth.DatabaseAuthBackend(connect=lambda: connection)

    with pytest.raises(auth.AuthError, match="Too many failed login attempts"):
        backend.authenticate_user(
            email="ada@example.com", password="wrong", ip_address="203.0.113.10"
        )

    queries = [query for query, _params in connection.cursor_obj.calls]
    assert any("pg_advisory_xact_lock" in query for query in queries)
    assert any("FROM login_attempts" in query for query in queries)
    assert not any("FROM users" in query for query in queries)
    assert connection.committed is False


def test_signup_creates_http_only_session_and_redirects_to_setup():
    backend = InMemoryAuthBackend()
    client = TestClient(create_app(auth_backend=backend))

    response = client.post(
        "/signup",
        data={"full_name": "Ada Agent", "email": "Ada@Example.com", "password": "super-secure-passphrase"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/setup"
    set_cookie = response.headers["set-cookie"]
    assert "groot_ops_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert backend.get_user_for_session(client.cookies.get("groot_ops_session")).email == "Ada@Example.com"


def test_signup_validation_keeps_user_on_form_without_session():
    backend = InMemoryAuthBackend()
    client = TestClient(create_app(auth_backend=backend))

    response = client.post(
        "/signup",
        data={"full_name": "A", "email": "not-an-email", "password": "short"},
    )

    assert response.status_code == 400
    assert "Create your Groot Ops account" in response.text
    assert "Enter a valid email address" in response.text
    assert "Password must be at least 12 characters" in response.text
    assert "groot_ops_session" not in client.cookies


def test_protected_routes_redirect_to_login_and_preserve_next(monkeypatch, tmp_path):
    monkeypatch.setenv("GROOT_OPS_DEMO_CONFIG_DIR", str(tmp_path))
    client = TestClient(create_app(auth_backend=InMemoryAuthBackend()))

    setup = client.get("/setup", follow_redirects=False)
    dashboard = client.get("/clients/evergreen/dashboard", follow_redirects=False)

    assert setup.status_code == 303
    assert setup.headers["location"] == "/login?next=%2Fsetup"
    assert dashboard.status_code == 303
    assert dashboard.headers["location"] == "/login?next=%2Fclients%2Fevergreen%2Fdashboard"


def test_dashboard_token_no_longer_unlocks_protected_routes(monkeypatch):
    monkeypatch.setenv("GROOT_OPS_DASHBOARD_TOKEN", "pilot-secret")
    client = TestClient(create_app(auth_backend=InMemoryAuthBackend()))

    response = client.get("/setup?token=pilot-secret", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")
    assert "groot_ops_dashboard_token" not in response.headers.get("set-cookie", "")


def test_login_sets_session_then_logout_revokes_it_and_blocks_dashboard(monkeypatch, tmp_path):
    monkeypatch.setenv("GROOT_OPS_DEMO_CONFIG_DIR", str(tmp_path))
    backend = InMemoryAuthBackend()
    backend.create_user(email="ada@example.com", password="super-secure-passphrase", full_name="Ada Agent")
    client = TestClient(create_app(auth_backend=backend))

    login = client.post(
        "/login?next=/setup",
        data={"email": "ada@example.com", "password": "super-secure-passphrase"},
        follow_redirects=False,
    )

    assert login.status_code == 303
    assert login.headers["location"] == "/setup"
    assert "groot_ops_session" in client.cookies
    assert client.get("/setup").status_code == 200

    logout = client.post("/logout", follow_redirects=False)

    assert logout.status_code == 303
    assert logout.headers["location"] == "/login?logged_out=1"
    assert "groot_ops_session" not in client.cookies
    assert client.get("/setup", follow_redirects=False).status_code == 303


def test_login_rejects_bad_credentials_without_setting_session():
    backend = InMemoryAuthBackend()
    backend.create_user(email="ada@example.com", password="super-secure-passphrase", full_name="Ada Agent")
    client = TestClient(create_app(auth_backend=backend))

    response = client.post("/login", data={"email": "ada@example.com", "password": "bad-password"})

    assert response.status_code == 401
    assert "Invalid email or password" in response.text
    assert "groot_ops_session" not in client.cookies


def test_signup_auth_backend_contract_uses_real_uuid_strings():
    user = auth.AuthUser(
        id="00000000-0000-0000-0000-000000000001",
        email="ada@example.com",
        full_name="Ada Agent",
        role="user",
        status="active",
    )

    assert UUID(user.id)
