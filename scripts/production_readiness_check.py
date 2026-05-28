from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    ".env.example",
    "configs/client.example.yaml",
    "configs/pilot_realtor.example.yaml",
    "docs/operator_runbook.md",
    "docs/client_onboarding_checklist.md",
    "docs/safety_policy.md",
    "docs/deployment_cron.md",
    "docs/sheet_schema.md",
]

FORBIDDEN_TRACKED_PATTERNS = [
    "configs/*.local.yaml",
    "configs/*rex*.yaml",
    "*.service-account.json",
]

SECRET_PATTERNS = [
    re.compile("-----BEGIN " + "PRIVATE KEY-----"),
    re.compile("AIza" + r"[0-9A-Za-z_-]{20,}"),
    re.compile("sk-" + r"[0-9A-Za-z_-]{20,}"),
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_required_files_exist() -> None:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).exists()]
    if missing:
        raise SystemExit(f"Missing production readiness files: {', '.join(missing)}")


def test_private_config_patterns_are_ignored() -> None:
    gitignore = _read(ROOT / ".gitignore")
    missing = [pattern for pattern in FORBIDDEN_TRACKED_PATTERNS if pattern not in gitignore]
    if missing:
        raise SystemExit(f".gitignore is missing private patterns: {', '.join(missing)}")


def test_no_obvious_secrets_in_repo_text_files() -> None:
    scanned_suffixes = {".py", ".md", ".yaml", ".yml", ".toml", ".example", ".txt"}
    violations: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {".git", ".venv", "__pycache__", ".pytest_cache"} for part in path.parts):
            continue
        if path.suffix not in scanned_suffixes and path.name != ".gitignore":
            continue
        content = _read(path)
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                violations.append(str(path.relative_to(ROOT)))
                break
    if violations:
        raise SystemExit(f"Potential secrets found: {', '.join(violations)}")


def main() -> None:
    test_required_files_exist()
    test_private_config_patterns_are_ignored()
    test_no_obvious_secrets_in_repo_text_files()
    print("Production readiness static check passed.")


if __name__ == "__main__":
    main()
