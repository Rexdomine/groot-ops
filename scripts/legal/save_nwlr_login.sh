#!/usr/bin/env bash
# Save the firm's NWLR Online login in OpenMausBot's vault on the GrootOps VPS, usable by Lex only.
#
# Run it yourself from this repo:   bash scripts/legal/save_nwlr_login.sh
# It asks for the email and password (the password is not shown as you type), sends them over SSH
# on standard input only (never in a command line, URL or file), and stores them sealed in the vault.
# Lex's browser then fills the NWLR Online sign-in form; the password is never shown to the bot.
#
# Options: SSH_HOST (default grootops-vps).
set -euo pipefail

SSH_HOST="${SSH_HOST:-grootops-vps}"

read -r -p "NWLR Online email: " NWLR_USER
read -r -s -p "NWLR Online password: " NWLR_PASS
echo
if [[ -z "$NWLR_USER" || -z "$NWLR_PASS" ]]; then
  echo "Both the email and the password are needed." >&2
  exit 1
fi

printf '%s\n%s\n' "$NWLR_USER" "$NWLR_PASS" | ssh -o BatchMode=yes "$SSH_HOST" 'python3 -I -c "
import json, sys, urllib.request, urllib.error
user = sys.stdin.readline().rstrip(chr(10))
password = sys.stdin.readline().rstrip(chr(10))
cfg = json.load(open(\"/etc/grootops-bridge/case-search.json\"))
api, bot = cfg[\"api_base\"].rstrip(\"/\"), cfg[\"bot_id\"]

def call(path, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(api + path, data=data, method=method or (\"POST\" if data else \"GET\"),
                                 headers={\"Content-Type\": \"application/json\"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b\"{}\")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b\"{}\")
        except ValueError:
            return e.code, {}

_, listing = call(\"/api/logins\")
existing = [l for l in listing.get(\"logins\", []) if l.get(\"site\") == \"nwlronline.com\" and l.get(\"source\") == \"settings\"]
login = {\"site\": \"nwlronline.com\", \"username\": user, \"password\": password, \"bots\": [bot]}
if existing:
    status, answer = call(\"/api/logins/\" + existing[0][\"id\"], login, method=\"PATCH\")
    action = \"Updated\"
else:
    status, answer = call(\"/api/logins\", login)
    action = \"Saved\"
if status >= 300:
    sys.exit(\"The vault refused the login (%s): %s\" % (status, answer.get(\"error\")))
print(action + \" the NWLR Online login for Lex.\")
"'
unset NWLR_USER NWLR_PASS
echo "Next: python -m groot_ops.main_case_search --check   (see docs/legal/case_search_prototype.md)"
