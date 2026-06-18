from __future__ import annotations

import pytest


def test_database_url_normalizes_sqlalchemy_postgres_scheme(monkeypatch):
    from groot_ops.db import database_url

    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@example.com/db?sslmode=require")

    assert database_url() == "postgresql://user:pass@example.com/db?sslmode=require"


def test_database_url_returns_none_when_missing(monkeypatch):
    from groot_ops.db import database_url

    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert database_url() is None


def test_safe_database_label_redacts_credentials():
    from groot_ops.db import safe_database_label

    label = safe_database_label(
        "postgresql://neondb_owner:super-secret@example.neon.tech/neondb?sslmode=require"
    )

    assert "super-secret" not in label
    assert "neondb_owner" not in label
    assert label == "example.neon.tech/neondb"


def test_check_database_ready_reports_missing_url(monkeypatch):
    from groot_ops.db import check_database_ready

    monkeypatch.delenv("DATABASE_URL", raising=False)

    readiness = check_database_ready()

    assert readiness.ok is False
    assert readiness.status == "missing_database_url"
    assert readiness.database is None


def test_check_database_ready_uses_connection_factory(monkeypatch):
    from groot_ops.db import check_database_ready

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, sql):
            self.sql = sql

        def fetchone(self):
            return (1,)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self):
            return FakeCursor()

    calls = []

    def fake_connect(url):
        calls.append(url)
        return FakeConnection()

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@example.com/neondb?sslmode=require")

    readiness = check_database_ready(connect=fake_connect)

    assert readiness.ok is True
    assert readiness.status == "ok"
    assert readiness.database == "example.com/neondb"
    assert calls == ["postgresql://user:pass@example.com/neondb?sslmode=require"]


def test_check_database_ready_redacts_connection_errors(monkeypatch, caplog):
    import logging

    from groot_ops.db import check_database_ready

    def fake_connect(url):
        raise RuntimeError(f"could not connect to {url}")

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@example.com/neondb")
    caplog.set_level(logging.WARNING)

    readiness = check_database_ready(connect=fake_connect)

    assert readiness.ok is False
    assert readiness.status == "connection_failed"
    assert "secret" not in (readiness.message or "")
    assert "user" not in (readiness.message or "")
    assert "example.com/neondb" in (readiness.message or "")
    log_text = caplog.text
    assert "RuntimeError" in log_text
    assert "example.com/neondb" in log_text
    assert "secret" not in log_text
    assert "user" not in log_text


def test_connect_database_uses_configurable_timeout(monkeypatch):
    import sys
    from types import SimpleNamespace

    from groot_ops.db import connect_database

    calls = []

    def fake_connect(url, *, connect_timeout):
        calls.append({"url": url, "connect_timeout": connect_timeout})
        return object()

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=fake_connect))
    monkeypatch.setenv("GROOT_OPS_DB_CONNECT_TIMEOUT", "7")

    connect_database("postgresql://user:***@example.com/neondb")

    assert calls == [
        {
            "url": "postgresql://user:***@example.com/neondb",
            "connect_timeout": 7,
        }
    ]
