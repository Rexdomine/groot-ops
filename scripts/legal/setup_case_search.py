"""Create or update the Lex research bot on the OpenMausBot server, and write the bridge's Case Search config.

Run on the VPS (standard library only), as root so it can write the bridge config:

    python3 setup_case_search.py --soul lex_soul.md

Idempotent: finds Lex by name, creates it if missing, then (re)applies its instructions and settings.
It never reads or writes a saved password; the NWLR Online login is added separately with save_nwlr_login.sh.
"""
from __future__ import annotations

import argparse
import grp
import json
import os
import sys
import urllib.error
import urllib.request

BOT_NAME = "Lex"
BOT_SETTINGS = {
    "title": "Legal Research (Pilot)",
    "description": "GrootOps Case Search: researches NWLR Online for Nigerian law firms.",
}
RUNTIME_SETTINGS = {
    # Its own browser on this server; no desktop, no connected apps, nothing sent on anyone's behalf.
    "computer": "browser",
    "browser": True,
    "approvalMode": "full",
    "outbound": {"policy": "ask"},
    # Lex only needs its browser: dropping unused tool groups and memory keeps every step's context small.
    "toolsOff": ["meetings", "data", "pages", "images", "email"],
    "memoryEnabled": False,
}


def call(api: str, path: str, body: dict | None = None, method: str | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(api.rstrip("/") + path, data=data, method=method or ("POST" if data else "GET"),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        raw = error.read() or b"{}"
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, {"error": raw[:300].decode(errors="replace")}


def find_bot(api: str) -> dict | None:
    status, data = call(api, "/api/bots")
    if status != 200:
        sys.exit(f"Could not list bots ({status}): {data.get('error')}")
    return next((b for b in data.get("bots", []) if b.get("name") == BOT_NAME), None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--soul", required=True, help="Lex's standing instructions (prompts/legal/lex_soul.md)")
    parser.add_argument("--api", default="http://127.0.0.1:8799")
    parser.add_argument("--config-out", default="/etc/grootops-bridge/case-search.json")
    parser.add_argument("--config-group", default="grootbridge", help="group that may read the config file")
    args = parser.parse_args()

    with open(args.soul, encoding="utf-8") as handle:
        soul = handle.read().strip()

    bot = find_bot(args.api)
    if bot is None:
        status, created = call(args.api, "/api/bots", {"name": BOT_NAME, **BOT_SETTINGS, "useDefaults": False})
        if status >= 300:
            sys.exit(f"Could not create {BOT_NAME} ({status}): {created.get('error')}")
        bot = created.get("bot") or created
        print(f"Created {BOT_NAME}: {bot.get('id')}")
    else:
        print(f"Found {BOT_NAME}: {bot['id']}")
    bot_id = bot["id"]

    for label, patch in (("instructions", {"soul": soul, **BOT_SETTINGS}), ("settings", RUNTIME_SETTINGS)):
        status, answer = call(args.api, f"/api/bots/{bot_id}", patch, method="PATCH")
        if status >= 300:
            sys.exit(f"Could not apply {label} ({status}): {answer.get('error')}")
        print(f"Applied {label}")

    config = {"bot_id": bot_id, "api_base": args.api}
    os.makedirs(os.path.dirname(args.config_out), exist_ok=True)
    with open(args.config_out, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
    try:
        os.chown(args.config_out, 0, grp.getgrnam(args.config_group).gr_gid)
        os.chmod(args.config_out, 0o640)
    except (KeyError, PermissionError) as error:
        print(f"Note: could not set group on {args.config_out}: {error}")
    print(f"Wrote {args.config_out}")


if __name__ == "__main__":
    main()
