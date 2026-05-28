# Phase 1.5 Production Readiness Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make Groot Ops safe, repeatable, testable, and pilot-ready before Phase 2 scheduled deployment.

**Architecture:** Keep the current lightweight Python package and Google Sheets/CSV repository abstraction. Add production readiness guardrails around secrets, CI, documentation, static checks, and operator runbooks without adding outbound sending.

**Tech Stack:** Python 3.10+, pytest, PyYAML, optional Google Sheets/Maton adapters, GitHub Actions.

---

## Task 1: Protect local secrets and client configs

**Objective:** Ensure private configs and credentials stay out of git.

**Files:**
- Modify: `.gitignore`
- Create: `.env.example`
- Create: `configs/client.example.yaml`

**Verification:**

```bash
git status --short
python scripts/production_readiness_check.py
```

## Task 2: Add CI

**Objective:** Run tests and readiness checks on every push/PR.

**Files:**
- Create: `.github/workflows/ci.yml`

**Verification:**

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python scripts/production_readiness_check.py
```

## Task 3: Add safety/deployment docs

**Objective:** Give Rex and future operators a clear production runbook.

**Files:**
- Create: `docs/safety_policy.md`
- Create: `docs/deployment_cron.md`
- Modify: `README.md`
- Modify: `docs/operator_runbook.md`
- Modify: `docs/client_onboarding_checklist.md`

**Verification:** Manually read docs for dry-run-first policy, approval policy, credential policy, and Phase 2 cron boundary.

## Task 4: Add readiness check script

**Objective:** Prevent missing readiness docs or obvious committed secrets.

**Files:**
- Create: `scripts/production_readiness_check.py`

**Verification:**

```bash
python scripts/production_readiness_check.py
```

## Task 5: Final validation and commit

**Objective:** Prove repo is ready to move into Phase 2 planning.

**Commands:**

```bash
python -m pytest -q
python scripts/production_readiness_check.py
git status --short
git add .
git commit -m "chore: add phase 1.5 production readiness"
git push -u origin HEAD
```
