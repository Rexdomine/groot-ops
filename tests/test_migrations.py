from __future__ import annotations

from pathlib import Path


def test_migration_files_are_discovered_in_order(tmp_path):
    from scripts.apply_migrations import discover_migrations

    (tmp_path / "002_second.sql").write_text("select 2;", encoding="utf-8")
    (tmp_path / "001_first.sql").write_text("select 1;", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")

    migrations = discover_migrations(tmp_path)

    assert [path.name for path in migrations] == ["001_first.sql", "002_second.sql"]


def test_first_migration_contains_required_tables():
    migration = Path("migrations/001_auth_and_clients.sql").read_text(encoding="utf-8")

    for table in [
        "schema_migrations",
        "users",
        "sessions",
        "email_verification_tokens",
        "password_reset_tokens",
        "login_attempts",
        "clients",
        "client_configs",
        "automation_runs",
        "audit_events",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration

    assert "password_hash" in migration
    assert "session_token_hash" in migration
    assert "token_hash" in migration
    assert "UNIQUE (email_normalized)" in migration
    assert "owner_user_id" in migration


def test_apply_pending_migrations_records_new_migration(tmp_path):
    from scripts.apply_migrations import apply_pending_migrations

    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "001_first.sql").write_text("CREATE TABLE demo(id integer);", encoding="utf-8")

    executed = []

    class FakeCursor:
        def __init__(self):
            self.query = ""
            self.params = None

        def execute(self, query, params=None):
            self.query = query
            self.params = params
            executed.append((query, params))

        def fetchall(self):
            return []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self):
            return FakeCursor()

    applied = apply_pending_migrations(FakeConnection(), migration_dir=migration_dir)

    assert applied == ["001_first.sql"]
    assert any("CREATE TABLE demo" in query for query, _params in executed)
    assert any("INSERT INTO schema_migrations" in query for query, _params in executed)


def test_apply_pending_migrations_skips_already_applied_migration(tmp_path):
    from scripts.apply_migrations import apply_pending_migrations

    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "001_first.sql").write_text("CREATE TABLE demo(id integer);", encoding="utf-8")

    executed = []

    class FakeCursor:
        def execute(self, query, params=None):
            executed.append((query, params))

        def fetchall(self):
            return [("001_first.sql",)]

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    applied = apply_pending_migrations(FakeConnection(), migration_dir=migration_dir)

    assert applied == []
    assert not any("CREATE TABLE demo" in query for query, _params in executed)
    assert not any("INSERT INTO schema_migrations" in query for query, _params in executed)


def test_apply_pending_migrations_dry_run_does_not_execute_migration_sql(tmp_path):
    from scripts.apply_migrations import apply_pending_migrations

    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "001_first.sql").write_text("CREATE TABLE demo(id integer);", encoding="utf-8")

    executed = []

    class FakeCursor:
        def execute(self, query, params=None):
            executed.append((query, params))

        def fetchall(self):
            return []

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    applied = apply_pending_migrations(FakeConnection(), migration_dir=migration_dir, dry_run=True)

    assert applied == ["001_first.sql"]
    assert not any("CREATE TABLE demo" in query for query, _params in executed)
    assert not any("INSERT INTO schema_migrations" in query for query, _params in executed)
