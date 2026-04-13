# Moodle Bot + Discord Control

A Moodle LMS automation bot that can:

- monitor assignments, grades, and course materials
- send Discord webhook notifications on detected changes
- download course files and generate AI study recommendations
- be controlled directly from Discord slash commands

## What This Bot Does

The project has two entrypoints:

- CLI runner: main.py
- Discord control runner: discord_bot.py

### Core capabilities

- Moodle login with saved browser session (Playwright)
- Scraping of:
  - dashboard assignments
  - course grades
  - course materials
- State diffing against previous run
- Discord webhook notifications for changes
- Optional AI analysis of downloaded files (Groq)
- Discord slash command control panel

## Discord Slash Commands

The bot provides these slash commands:

- /ping
  - Health check.
- /status
  - Shows run lock status and last monitor run time.
- /monitor_now
  - Runs full monitor cycle now (scrape + diff + notify).
- /assignments_now
  - Returns current assignments snapshot.
- /grades_now
  - Returns current grades snapshot.
- /analyze
  - Analyze one course by ID/name filter, or all selected if omitted.
- /analyze_all
  - Build one unified analysis report across selected/all courses.
- /login_refresh
  - Forces a fresh Moodle login and updates saved browser session.

## Project Structure

- main.py: CLI entrypoint
- discord_bot.py: Discord slash-command bot
- services.py: shared orchestration used by CLI and Discord bot
- login.py: Playwright authentication/session persistence
- scraper.py: course/assignment/grade/material scraping
- differ.py: state load/save + change detection
- notifier.py: Discord webhook formatting/sending
- downloader.py: file download helpers
- extractor.py: text extraction from PDF/PPTX
- analyzer.py: Groq-based recommendation generation
- config.py: environment and constants
- data/: state, browser session, downloads, generated analyses

## Setup

### 1) Prerequisites

- Python 3.11+
- pip
- Playwright browser runtime

### 2) Create and activate virtual environment

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3) Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 4) Configure environment

Copy .env.example to .env and fill values:

```bash
cp .env.example .env
```

Required values:

- MOODLE_URL
- DISCORD_WEBHOOK_URL
- GROQ_API_KEY (needed for analyze features)
- DISCORD_BOT_TOKEN (needed for slash-command control)

Optional Discord control values:

- DISCORD_ALLOWED_USER_IDS (comma-separated user IDs)
- DISCORD_ALLOWED_ROLE_IDS (comma-separated role IDs)
- DISCORD_CONTROL_GUILD_ID (recommended for fast command sync)

## Running

### CLI mode

First baseline run (no notifications):

```bash
python main.py --first-run --headed
```

Normal monitor run:

```bash
python main.py
```

Debug dry run:

```bash
python main.py --verbose --dry-run
```

Analyze selected courses:

```bash
python main.py --analyze
```

Unified analysis across courses:

```bash
python main.py --analyze-all
```

### Discord control mode

Run the bot:

```bash
python discord_bot.py
```

If your shell points to a different Python, run with explicit venv interpreter:

```bash
.venv/bin/python discord_bot.py
```

## Example Discord Interactions

### Health check

User:

```text
/ping
```

Bot:

```text
Pong. Moodle control bot is running.
```

### Snapshot assignments

User:

```text
/assignments_now
```

Bot (example):

```text
Assignments: 3

- [Machine Learning] Homework 4
  Due: 2026-04-20 23:59
- [Algorithms] Project Proposal
  Due: 2026-04-18 17:00
- [Software Engineering] Sprint Report
  Due: N/A
```

### Trigger monitor

User:

```text
/monitor_now
```

Bot (example):

```text
Monitor completed. Summary: 2 new assignments, 1 grade update, 0 new materials
```

### Course analysis

User:

```text
/analyze course:Machine Learning
```

Bot (example):

```text
Generated 1 analysis file(s):
- Machine_Learning_analysis.md
```

## Troubleshooting

### Slash commands show but do not respond

- Check channel permissions for the bot:
  - View Channel
  - Send Messages
  - Use Application Commands
- Ensure bot invite includes both scopes:
  - bot
  - applications.commands
- Set DISCORD_CONTROL_GUILD_ID for fast guild sync and restart bot.

### ModuleNotFoundError for discord or groq

Install dependencies in the same interpreter used to run the bot:

```bash
python -m pip install -r requirements.txt
```

or

```bash
.venv/bin/python -m pip install -r requirements.txt
```

### Analyze commands fail because optional libs are missing

Install optional analyze dependencies:

```bash
pip install groq pdfplumber python-pptx
```

## Security Notes

- Never commit real .env secrets.
- Rotate exposed webhook/API/bot tokens immediately if leaked.
- Keep .env only on trusted machines.
