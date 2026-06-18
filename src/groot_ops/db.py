from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from typing import Any, Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatabaseReadiness:
    ok: bool
    status: str
    database: str | None = None
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def database_url() -> str | None:
    """Return the configured Postgres URL, normalized for modern drivers."""
    configured = os.getenv("DATABASE_URL", "").strip()
    if not configured:
        return None
    if configured.startswith("postgres://"):
        return "postgresql://" + configured[len("postgres://") :]
    return configured


def safe_database_label(url: str | None = None) -> str | None:
    """Return a credential-free host/database label for logs and readiness output."""
    resolved_url = url or database_url()
    if not resolved_url:
        return None
    parsed = urlparse(resolved_url)
    host = parsed.hostname or "unknown-host"
    database = (parsed.path or "").lstrip("/") or "unknown-db"
    return f"{host}/{database}"


def connect_database(url: str | None = None) -> Any:
    """Create a Postgres connection.

    Import psycopg lazily so tests and non-DB local workflows can import the app without
    immediately requiring a live database driver.
    """
    resolved_url = url or database_url()
    if not resolved_url:
        raise RuntimeError("DATABASE_URL is not configured")

    timeout = int(os.getenv("GROOT_OPS_DB_CONNECT_TIMEOUT", "5"))

    import psycopg

    return psycopg.connect(resolved_url, connect_timeout=timeout)


def check_database_ready(
    *, connect: Callable[[str], Any] | None = None
) -> DatabaseReadiness:
    """Run a lightweight DB readiness check without exposing credentials."""
    resolved_url = database_url()
    label = safe_database_label(resolved_url)
    if not resolved_url:
        return DatabaseReadiness(
            ok=False,
            status="missing_database_url",
            message="DATABASE_URL is not configured",
        )

    connector = connect or connect_database
    try:
        with connector(resolved_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                row = cur.fetchone()
        if row != (1,):
            return DatabaseReadiness(
                ok=False,
                status="unexpected_database_response",
                database=label,
                message="Database responded unexpectedly to readiness query",
            )
        return DatabaseReadiness(ok=True, status="ok", database=label)
    except Exception as exc:
        logger.warning(
            "database readiness check failed for %s: %s",
            label or "unconfigured-database",
            exc.__class__.__name__,
        )
        return DatabaseReadiness(
            ok=False,
            status="connection_failed",
            database=label,
            message=f"Could not connect to {label}: {exc.__class__.__name__}",
        )
