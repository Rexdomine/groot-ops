"""Run Case Search from the command line.

    python -m groot_ops.main_case_search --check                 # is everything ready?
    python -m groot_ops.main_case_search --question "..."        # one live search
    python -m groot_ops.main_case_search --eval                  # the pilot's test questions, to a report

The OpenMausBot API must be reachable at api_base (see configs/legal/case_search_pilot.yaml for the SSH tunnel).
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

from groot_ops.case_search import CaseSearch, format_for_chat, format_markdown, preflight

DEFAULT_CONFIG = "configs/legal/case_search_pilot.yaml"


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def run_check(api: str, bot_id: str) -> bool:
    checks = preflight(api, bot_id)
    for check in checks:
        print(f"[{'ok' if check.ok else '--'}] {check.name}: {check.detail}")
    ready = all(check.ok for check in checks)
    print("Ready for a live search." if ready else "Not ready yet: fix the items marked --.")
    return ready


def run_eval(search: CaseSearch, questions: list[str], out: Path) -> None:
    sections = [f"# Case Search evaluation, {datetime.now():%Y-%m-%d %H:%M}", ""]
    for number, question in enumerate(questions, 1):
        print(f"[{number}/{len(questions)}] {question}", flush=True)
        started = time.monotonic()
        result = search.search(question)
        seconds = time.monotonic() - started
        print(f"    {result.status}: {len(result.authorities)} kept, {len(result.rejected)} rejected, {seconds:.0f}s")
        sections += [format_markdown(question, result), f"_Took {seconds:.0f} seconds._", ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(sections), encoding="utf-8")
    print(f"Report: {out}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GrootOps Case Search over NWLR Online, through the Lex bot.")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--api", help="OpenMausBot API base (overrides the config)")
    parser.add_argument("--bot-id", help="Lex's bot id (overrides the config)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="check everything is ready, without searching")
    mode.add_argument("--question", help="run one search and print the answer as a lawyer would see it")
    mode.add_argument("--eval", action="store_true", help="run the config's test questions and write a report")
    parser.add_argument("--out", help="report path for --eval (default data/legal/case-search-eval-<time>.md)")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    api, bot_id = args.api or config.get("api_base"), args.bot_id or config.get("bot_id")
    if not api or not bot_id:
        parser.error("set api_base and bot_id in the config, or pass --api and --bot-id")

    try:
        if args.check:
            return 0 if run_check(api, bot_id) else 1
        search = CaseSearch(api, bot_id)
        if args.question:
            result = search.search(args.question, on_wait=lambda: print(".", end="", flush=True))
            print()
            print(format_for_chat(args.question, result))
            return 0 if result.status in ("ok", "no_results") else 1
        out = Path(args.out or f"data/legal/case-search-eval-{datetime.now():%Y%m%d-%H%M}.md")
        run_eval(search, list(config.get("eval_questions") or []), out)
        return 0
    except OSError as error:
        print(f"Could not reach OpenMausBot at {api}: {error}. Is the SSH tunnel open?", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
