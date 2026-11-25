# Case Search prototype (NWLR Online)

Case Search answers a lawyer's research question with ranked authorities from NWLR Online. Every case it returns has an exact citation, a verbatim quote and a link to the report it was taken from. It is the first GrootOps Legal feature (see the build plan doc).

Status on 2026-11-23: everything is set up on the VPS. The only missing piece is the firm's NWLR Online login.

## How it works

1. A lawyer sends `/search <question>` to the GrootOps Telegram bot, or we run it from the command line.
2. The bridge (`src/groot_ops/case_search.py`) sends the question to **Lex**, an OpenMausBot bot on the VPS. Each search starts with a fresh context, and searches queue one at a time.
3. Lex opens NWLR Online in its own browser on the VPS and signs in with the login saved in OpenMausBot's vault. It runs 3 to 6 searches, reads the cases, and replies with one JSON block. Its instructions are in `prompts/legal/lex_soul.md`.
4. `verify()` keeps only authorities that pass three checks:
   - the citation is in a recognised Nigerian law-report format (NWLR, LPELR, All FWLR, SC, SCNJ and others);
   - there is a verbatim quote of 120 words or fewer;
   - the source link is an https case page on nwlronline.com.

   Anything that fails is listed as rejected, with the reason.
5. The lawyer gets the answer, the authorities with quotes and links, and a reminder to check each one before relying on it.

## What is on the VPS

| Piece | Where |
| --- | --- |
| Lex bot | OpenMausBot bot `2ef1a866-b51d-47a1-8f06-3d78bbd2dfa1`: browser computer, full access, outbound sends set to Ask, no connected apps |
| Browser | agent-browser 0.37.0 with Chrome 158, copied root-owned to `/opt/openmausbot-browser/chrome-158.0.8127.36` and allowed by the AppArmor profile `/etc/apparmor.d/openmausbot-chrome` (Ubuntu 24.04 sandbox fix from the OpenMausBot deploy guide). Service env: `/etc/systemd/system/openmausbot.service.d/browser.conf` |
| Bridge config | `/etc/grootops-bridge/case-search.json` (bot id and API address only, no secrets). Turned on by `/etc/systemd/system/grootops-bridge.service.d/case-search.conf` |
| NWLR login | OpenMausBot vault, site `nwlronline.com`, limited to Lex. **Not saved yet.** |

After a Chrome update, copy the new version and update both the AppArmor profile and `browser.conf`. The root-owned copy does not update itself.

## Go live: save the login, check, test

1. Save the NWLR Online login. Run this yourself; it asks for the email and password and never shows or stores them anywhere except the vault:

   ```bash
   bash scripts/legal/save_nwlr_login.sh
   ```

2. Open a tunnel to the VPS in a second terminal and leave it running:

   ```bash
   ssh -N -L 18799:127.0.0.1:8799 grootops-vps
   ```

3. Check everything is ready (every line should say ok):

   ```bash
   .venv/bin/python -m groot_ops.main_case_search --check
   ```

4. Run one search, then the three test questions from the lawyer meeting (the report goes to `data/legal/`):

   ```bash
   .venv/bin/python -m groot_ops.main_case_search --question "Grounds to set aside an incompetent writ of summons"
   ```

   ```bash
   .venv/bin/python -m groot_ops.main_case_search --eval
   ```

5. Watch a search live in the GrootOps web app: Lex's chat shows the browser as it works.

## Web app (GrootOps Legal)

Lawyers use a chat-style web app at **https://legal.207-180-242-149.sslip.io**. It has search history down the side, live research steps with the animated orb, case cards (copy citation, open on NWLR, save), thumbs up/down, saved authorities and a Word memo export. It is separate from the real estate product: its own service, user, database and address. The real estate Telegram bot no longer has `/search`; a dedicated legal Telegram bot comes later.

| Piece | Where |
| --- | --- |
| Code | `src/groot_ops/legal/` (FastAPI app, SQLite store, search runner, memo builder, static chat UI) |
| Service | `grootops-legal` systemd unit, user `grootlegal`, uvicorn on 127.0.0.1:8820, Python venv in `/opt/grootops-legal/venv` |
| Data | `/var/lib/grootops-legal/legal.sqlite3`: accounts, sessions, searches, saved authorities |
| HTTPS | the existing `grootops-caddy` container; block in `/etc/grootops-caddy/Caddyfile` (the sslip.io name points at the VPS, and Caddy gets the certificate itself) |

Add a lawyer account (on the VPS; the password is typed at a hidden prompt):

```bash
ssh -t grootops-vps 'grootops-legal-user add-user --email ada@firm.ng --name "Ada Obi" --firm "Pilot Chambers"'
```

Deploy code changes:

```bash
rsync -a --delete --exclude __pycache__ src/groot_ops/ grootops-vps:/opt/grootops-legal/src/groot_ops/ && ssh grootops-vps 'systemctl restart grootops-legal'
```

Preview the design locally with sample results (clearly labelled), no Lex needed:

```bash
LEGAL_PREVIEW=1 LEGAL_DB=/tmp/legal-preview.sqlite3 PYTHONPATH=src .venv/bin/uvicorn --factory groot_ops.legal.app:create_app --port 8820
```

The sidebar's status line shows "NWLR Online connected" once the login is saved, and "NWLR login needed" until then. A restart of the service marks any unfinished search as failed, with a Try again link.

## Keeping NWLR Online from blocking us

NWLR Online sits behind Cloudflare. When our server loads too many pages it shows a security check
("Performing security verification", HTTP 429). Lex never tries to pass it: it stops, returns what it has
verified, and the app holds new searches. Never add proxies, browser disguises or challenge solving.

- **Page budget** (`src/groot_ops/legal/nwlr.py`): the app counts every NWLR page Lex opens and starts a search
  only if it fits 12 pages per hour; after any security check it holds searches for 2 hours. Lawyers see when
  a waiting search will start. NWLR's real threshold isn't published: it blocked at about 16 pages in an hour.
- **Cache**: an identical question within 30 days gets its verified result again (no pages, no tokens). A similar
  question hands Lex the authorities it already verified, so it opens fewer reports or none. Only citations,
  short quotes, holdings and links are stored, never report text.
- **Pacing in Lex**: its two report readers pause between pages, and it may not write its own.

Measured on 2026-11-25 (Lex on `claude-sonnet-5-5`): a fresh search takes 70-130 s, about $0.18-0.29 and 4-11
NWLR pages; a similar question answered from the cache took 22 s, $0.06 and no pages. Sonnet 5 cost
$0.24-0.45; Haiku 5.5 was much cheaper but found too few authorities.

Longer term the fix is our own licensed collection of judgments (for example Judy.legal or Laws.Africa,
NigeriaLII's publisher) for finding cases, with NWLR used only for the citation, plus talks with NWLR.
NigeriaLII alone isn't enough: its Supreme Court and Court of Appeal judgments stop at 2017, it had 3 of our
10 benchmark cases, and its robots.txt reserves AI use (`ai-input=no`), so written permission is needed.

## Pilot pass mark (proposed in the build plan)

At least 3 relevant authorities per test question that the lawyer agrees are on point, no invented citations, an answer in under 5 minutes, and better than their manual search on 2 of the 3 questions.

## Known limits

- The source check proves the link is a case page on NWLR Online, not that the quote appears on it. The lawyer still checks before filing; a quote-on-page check is the next step.
- One search at a time. A second question waits for the first to finish, and the page budget allows about 2 fresh searches an hour.
- LawPavilion (a desktop app) is not covered yet; it needs a Windows cloud desktop.
- Use stays within the pilot lawyer's written permission to use their login. Check the NWLR Online subscription terms before using it more widely.
