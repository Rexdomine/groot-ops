from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MIGRATION_DIR = ROOT / "migrations"
SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    name text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def load_local_env(path: Path = ROOT / ".env") -> None:
    """Load simple KEY=VALUE pairs from .env without printing secrets."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def discover_migrations(migration_dir: Path = DEFAULT_MIGRATION_DIR) -> list[Path]:
    return sorted(path for path in migration_dir.glob("*.sql") if path.is_file())


def _cursor_fetchall(cur: Any) -> list[Any]:
    result = cur.fetchall()
    return list(result or [])


def _cursor_fetchone(cur: Any) -> Any:
    if hasattr(cur, "fetchone"):
        return cur.fetchone()
    rows = _cursor_fetchall(cur)
    return rows[0] if rows else None


def applied_migration_names(conn: Any, *, ensure_table: bool = True) -> set[str]:
    cur = conn.cursor()
    if ensure_table:
        cur.execute(SCHEMA_MIGRATIONS_DDL)
    else:
        cur.execute("SELECT to_regclass('public.schema_migrations')")
        row = _cursor_fetchone(cur)
        if not row or row[0] is None:
            return set()
    cur.execute("SELECT name FROM schema_migrations")
    return {row[0] for row in _cursor_fetchall(cur)}


def pending_migration_paths(
    conn: Any, *, migration_dir: Path = DEFAULT_MIGRATION_DIR, ensure_schema_table: bool = True
) -> list[Path]:
    applied = applied_migration_names(conn, ensure_table=ensure_schema_table)
    return [path for path in discover_migrations(migration_dir) if path.name not in applied]


def pending_migration_names(
    conn: Any, *, migration_dir: Path = DEFAULT_MIGRATION_DIR, ensure_schema_table: bool = True
) -> list[str]:
    return [
        path.name
        for path in pending_migration_paths(
            conn, migration_dir=migration_dir, ensure_schema_table=ensure_schema_table
        )
    ]


def apply_pending_migrations(
    conn: Any, *, migration_dir: Path = DEFAULT_MIGRATION_DIR, dry_run: bool = False
) -> list[str]:
    cur = conn.cursor()
    pending = pending_migration_paths(
        conn,
        migration_dir=migration_dir,
        ensure_schema_table=not dry_run,
    )

    applied_now: list[str] = []
    for migration in pending:
        sql = migration.read_text(encoding="utf-8")
        if dry_run:
            applied_now.append(migration.name)
            continue
        cur.execute(sql)
        cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (migration.name,))
        applied_now.append(migration.name)

    if not dry_run and hasattr(conn, "commit"):
        conn.commit()
    return applied_now


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Groot Ops database migrations.")
    parser.add_argument("--dry-run", action="store_true", help="List pending migrations without applying them.")
    args = parser.parse_args()

    load_local_env()

    from groot_ops.db import connect_database, database_url, safe_database_label

    if not database_url():
        raise SystemExit("DATABASE_URL is not configured")

    label = safe_database_label()
    if args.dry_run:
        with connect_database() as conn:
            migrations = pending_migration_names(conn, ensure_schema_table=False)
        print(f"Pending {len(migrations)} migration(s) for {label}:")
        for migration_name in migrations:
            print(f"- {migration_name}")
        return

    with connect_database() as conn:
        applied = apply_pending_migrations(conn)
    if applied:
        print(f"Applied {len(applied)} migration(s) to {label}:")
        for migration_name in applied:
            print(f"- {migration_name}")
    else:
        print(f"No pending migrations for {label}.")


if __name__ == "__main__":
    main()
