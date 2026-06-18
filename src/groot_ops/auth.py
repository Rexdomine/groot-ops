from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import connect_database

HASH_ALGORITHM = "pbkdf2_sha256"
HASH_ITERATIONS = 260_000
LOGIN_RATE_LIMIT_MAX_FAILURES = 5
LOGIN_RATE_LIMIT_WINDOW_MINUTES = 15
SESSION_COOKIE_NAME = "groot_ops_session"
SESSION_DAYS = 14


class AuthError(Exception):
    """Expected authentication/validation failure safe to show to users."""


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str
    full_name: str
    role: str
    status: str


@dataclass(frozen=True)
class AuthSession:
    user: AuthUser
    token: str
    expires_at: datetime


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str, *, iterations: int = HASH_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{HASH_ALGORITHM}${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iteration_text, salt_text, digest_text = stored_hash.split("$", 3)
        if algorithm != HASH_ALGORITHM:
            return False
        iterations = int(iteration_text)
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ip_hash_secret() -> str:
    secret = os.getenv("GROOT_OPS_IP_HASH_SECRET") or os.getenv("GROOT_OPS_SESSION_SECRET")
    if not secret:
        raise RuntimeError(
            "Set GROOT_OPS_IP_HASH_SECRET or GROOT_OPS_SESSION_SECRET before hashing IP addresses."
        )
    return secret


def hash_ip_address(ip_address: str) -> str:
    cleaned = (ip_address or "").strip()
    if not cleaned:
        return ""
    return hmac.new(_ip_hash_secret().encode("utf-8"), cleaned.encode("utf-8"), hashlib.sha256).hexdigest()


def _login_rate_limit_lock_key(scope: str, value: str) -> int:
    digest = hashlib.sha256(f"login-rate-limit:{scope}:{value}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def _user_from_row(row: Any) -> AuthUser:
    return AuthUser(
        id=str(row[0]),
        email=str(row[1]),
        full_name=str(row[2]),
        role=str(row[3]),
        status=str(row[4]),
    )


class DatabaseAuthBackend:
    def __init__(self, *, connect: Any = connect_database) -> None:
        self._connect = connect

    def create_user(self, *, email: str, password: str, full_name: str) -> AuthUser:
        email_clean = email.strip()
        full_name_clean = full_name.strip()
        email_normalized = normalize_email(email_clean)
        password_hash = hash_password(password)
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO users (email, email_normalized, password_hash, full_name, role, status)
                        VALUES (%s, %s, %s, %s, 'user', 'active')
                        RETURNING id, email, full_name, role, status
                        """,
                        (email_clean, email_normalized, password_hash, full_name_clean),
                    )
                    row = cur.fetchone()
                conn.commit()
        except Exception as exc:
            if "users_email_normalized" in str(exc) or "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
                raise AuthError("An account with this email already exists.") from exc
            raise
        if not row:
            raise AuthError("Could not create account.")
        return _user_from_row(row)

    def authenticate_user(
        self, *, email: str, password: str, user_agent: str = "", ip_address: str = ""
    ) -> AuthSession:
        email_normalized = normalize_email(email)
        ip_hash = hash_ip_address(ip_address)
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    self._lock_login_rate_limit_bucket(
                        cur, email_normalized=email_normalized, ip_hash=ip_hash
                    )
                    self._raise_if_login_rate_limited(cur, email_normalized=email_normalized, ip_hash=ip_hash)
                    cur.execute(
                        """
                        SELECT id, email, full_name, role, status, password_hash
                        FROM users
                        WHERE email_normalized = %s
                        """,
                        (email_normalized,),
                    )
                    row = cur.fetchone()
                    if not row or row[4] != "active" or not verify_password(password, str(row[5])):
                        cur.execute(
                            """
                            INSERT INTO login_attempts (email_normalized, ip_hash, success, reason)
                            VALUES (%s, %s, false, %s)
                            """,
                            (email_normalized, ip_hash, "invalid_credentials"),
                        )
                        conn.commit()
                        raise AuthError("Invalid email or password.")

                    user = _user_from_row(row)
                    token = generate_session_token()
                    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
                    cur.execute(
                        """
                        INSERT INTO sessions (user_id, session_token_hash, user_agent, ip_hash, expires_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (user.id, hash_session_token(token), user_agent[:512], ip_hash, expires_at),
                    )
                    cur.execute(
                        "UPDATE users SET last_login_at = now(), updated_at = now() WHERE id = %s",
                        (user.id,),
                    )
                    cur.execute(
                        """
                        INSERT INTO login_attempts (email_normalized, ip_hash, success, reason)
                        VALUES (%s, %s, true, %s)
                        """,
                        (email_normalized, ip_hash, "login"),
                    )
                conn.commit()
            return AuthSession(user=user, token=token, expires_at=expires_at)
        except AuthError:
            raise

    def _lock_login_rate_limit_bucket(self, cur: Any, *, email_normalized: str, ip_hash: str) -> None:
        lock_keys = set()
        if email_normalized:
            lock_keys.add(_login_rate_limit_lock_key("email", email_normalized))
        if ip_hash:
            lock_keys.add(_login_rate_limit_lock_key("ip", ip_hash))
        for lock_key in sorted(lock_keys):
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))

    def _raise_if_login_rate_limited(self, cur: Any, *, email_normalized: str, ip_hash: str) -> None:
        cur.execute(
            """
            SELECT count(*)
            FROM login_attempts
            WHERE success = false
              AND created_at >= now() - (%s * interval '1 minute')
              AND (email_normalized = %s OR (%s <> '' AND ip_hash = %s))
            """,
            (LOGIN_RATE_LIMIT_WINDOW_MINUTES, email_normalized, ip_hash, ip_hash),
        )
        row = cur.fetchone()
        failed_attempts = int(row[0]) if row else 0
        if failed_attempts >= LOGIN_RATE_LIMIT_MAX_FAILURES:
            raise AuthError("Too many failed login attempts. Please wait 15 minutes and try again.")

    def create_session(
        self, *, user_id: str, user_agent: str = "", ip_address: str = ""
    ) -> AuthSession:
        token = generate_session_token()
        expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
        ip_hash = hash_ip_address(ip_address)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, email, full_name, role, status
                    FROM users
                    WHERE id = %s AND status = 'active'
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise AuthError("User account is not active.")
                user = _user_from_row(row)
                cur.execute(
                    """
                    INSERT INTO sessions (user_id, session_token_hash, user_agent, ip_hash, expires_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (user.id, hash_session_token(token), user_agent[:512], ip_hash, expires_at),
                )
            conn.commit()
        return AuthSession(user=user, token=token, expires_at=expires_at)

    def get_user_for_session(self, token: str) -> AuthUser | None:
        if not token:
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT u.id, u.email, u.full_name, u.role, u.status
                    FROM sessions s
                    JOIN users u ON u.id = s.user_id
                    WHERE s.session_token_hash = %s
                      AND s.revoked_at IS NULL
                      AND s.expires_at > now()
                      AND u.status = 'active'
                    """,
                    (hash_session_token(token),),
                )
                row = cur.fetchone()
                if not row:
                    return None
                cur.execute(
                    "UPDATE sessions SET last_seen_at = now() WHERE session_token_hash = %s",
                    (hash_session_token(token),),
                )
            conn.commit()
        return _user_from_row(row)

    def revoke_session(self, token: str) -> None:
        if not token:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sessions
                    SET revoked_at = COALESCE(revoked_at, now()), last_seen_at = now()
                    WHERE session_token_hash = %s AND revoked_at IS NULL
                    """,
                    (hash_session_token(token),),
                )
            conn.commit()
