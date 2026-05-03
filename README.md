# Nachrichtenüberblick — Weekly Auto-Filled Worksheet

Automated pipeline that fills the school "Aktuelle Stunde" PDF every Wednesday at 23:20 Berlin time.

**Topic 3 and the personal reflection are intentionally left blank** — fill those by hand, or leave them. The system **never submits anything** — it only delivers a review-ready PDF to Telegram so you can check it before class.

## How it works

```
Wed 23:20 Berlin · GitHub Actions cron
        │
        ▼
   src/main.py build
   ├─ news_fetcher       Tagesschau API + ZDF/DLF/SZ/ZEIT RSS
   ├─ topic_selector     Claude picks 2 topics + matching second sources
   ├─ content_generator  Claude → German bullets, schema-validated
   └─ pdf_filler         PyMuPDF overlay onto template/vorlage_nachrichten.pdf
        │
        ▼
   git commit output/<YYYY-MM-DD>.pdf  →  raw.githubusercontent.com
        │
        ▼
   src/main.py notify    POST to n8n webhook (PDF URL + summary)
        │
        ▼
   n8n  ──►  Telegram: text summary + PDF document
```

## One-time setup

### 1. Add GitHub secrets

In the repo: **Settings → Secrets and variables → Actions → New repository secret**.

| Secret               | Value                                                      |
|----------------------|------------------------------------------------------------|
| `ANTHROPIC_API_KEY`  | `sk-ant-...` from console.anthropic.com                    |
| `N8N_WEBHOOK_URL`    | The webhook URL n8n shows you after activating the flow    |

### 2. Create a Telegram bot

1. Open Telegram → search `@BotFather` → `/newbot`. Pick any name. Save the token (`123456:ABC...`).
2. Send any message to your new bot from your Telegram account (so the bot can DM you back).
3. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser. Find `"chat":{"id":NNNNNN}` — that's your `TELEGRAM_CHAT_ID`.

### 3. Wire the n8n workflow

In your n8n instance:

1. **Credentials → New → Telegram API** → paste the bot token. Save it as e.g. `Telegram Bot`.
2. **Settings → Variables** (or environment): add `TELEGRAM_CHAT_ID` = your chat ID.
3. **Workflows → Import from File** → upload `n8n-workflow.json`.
4. Open the two Telegram nodes (`Telegram: Send Summary`, `Telegram: Send PDF`) and select the credential you just created (the JSON has a placeholder `REPLACE_WITH_TELEGRAM_CREDENTIAL_ID`).
5. **Activate** the workflow. Copy the **Production webhook URL** shown on the Webhook node — paste it into the `N8N_WEBHOOK_URL` GitHub secret.

### 4. Trigger a manual test run

In GitHub: **Actions → Weekly Nachrichtenueberblick → Run workflow**.

Within ~2 minutes you should receive in Telegram:
- A summary message with both topic titles + source links
- The filled PDF as a document attachment

## Local development

```bash
python -m venv .venv && .venv\Scripts\activate         # Windows PowerShell
pip install -r requirements.txt
copy .env.example .env.local                            # then edit values

# Phase-by-phase smoke tests:
python tests/inspect_template.py                        # dump label coordinates
python -m src.pdf_filler --static                       # PDF with hardcoded German content
python -m src.news_fetcher                              # 20+ candidates → tests/candidates.json
python -m src.topic_selector                            # selects 2 topics → tests/article_pairs.json
python -m src.content_generator --mock-articles tests/fixtures/articles.json

# Full pipeline (creates output/<date>.pdf):
python -m src.main build
```

## File map

| Path                                      | Purpose                                                  |
|-------------------------------------------|----------------------------------------------------------|
| `template/vorlage_nachrichten.pdf`        | School template (committed, not modified)                |
| `config/field_coords.json`                | (x,y) rectangles per field                               |
| `config/prompts.py`                       | German system prompt + banned-phrase list                |
| `src/main.py`                             | Orchestrator (`build` + `notify` subcommands)            |
| `src/news_fetcher.py`                     | Tagesschau API + RSS feeds                               |
| `src/topic_selector.py`                   | Claude picks 2 topics + validates URLs/dates             |
| `src/content_generator.py`                | Claude → schema-validated German bullets                 |
| `src/pdf_filler.py`                       | PyMuPDF text overlay                                     |
| `src/webhook_sender.py`                   | POST to n8n                                              |
| `.github/workflows/weekly.yml`            | Wednesday 23:20 Berlin cron                              |
| `n8n-workflow.json`                       | Importable n8n workflow                                  |
| `tests/inspect_template.py`               | Dump every text span + bbox from the template            |
| `tests/fixtures/articles.json`            | Mock article pairs for offline content-gen testing       |
| `output/`                                 | Generated PDFs (one per week, committed by Action)       |

## Safety notes

- The Telegram message **always** includes `⚠️ Bitte vor Abgabe prüfen.`
- Both source URLs appear in the message so you can spot-check before class.
- A `presentation_blurb` per topic explains how to talk about it for 1–2 minutes.
- **No automatic submission anywhere.** Output is delivery-only.
- If any phase fails (no good topics, source 404, content overflow, n8n unreachable), the GitHub Action exits non-zero and emails you the failure.

## Calibration

If a field overflows or text lands in the wrong spot:

1. Run `python tests/inspect_template.py` to dump the label positions.
2. Adjust the rect in `config/field_coords.json` (origin is top-left, units = points, A4 = 595.3×841.9).
3. Re-run `python -m src.pdf_filler --static` and inspect `tests/output_static.pdf`.

## DST note

Cron runs in UTC (`20 22 * * 3`). Mid-Mar to late-Oct (CEST), the actual fire time is 00:20 Thursday Berlin instead of 23:20 Wednesday — acceptable drift for a school worksheet.
