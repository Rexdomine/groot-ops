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

## Pilot pass mark (proposed in the build plan)

At least 3 relevant authorities per test question that the lawyer agrees are on point, no invented citations, an answer in under 5 minutes, and better than their manual search on 2 of the 3 questions.

## Known limits

- The source check proves the link is a case page on NWLR Online, not that the quote appears on it. The lawyer still checks before filing; a quote-on-page check is the next step.
- One search at a time. A second question waits for the first to finish.
- LawPavilion (a desktop app) is not covered yet; it needs a Windows cloud desktop.
- Use stays within the pilot lawyer's written permission to use their login. Check the NWLR Online subscription terms before using it more widely.
