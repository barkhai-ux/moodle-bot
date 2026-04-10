# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Moodle LMS scraper bot that monitors courses for changes and sends Discord notifications. It can also download course materials, extract text, and generate AI-powered study recommendations via Groq.

## Running

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Additional dependencies for the --analyze feature (not in requirements.txt)
pip install pdfplumber python-pptx groq

# First run (saves initial state, no notifications sent)
python main.py --first-run --headed

# Normal run (headless, sends Discord notifications on changes)
python main.py

# Force re-login (opens browser for Google OAuth)
python main.py --login

# Download materials and generate AI study recommendations
python main.py --analyze

# Debug output
python main.py --verbose --dry-run
```

## Configuration

All config is in `.env` with three values: `MOODLE_URL`, `DISCORD_WEBHOOK_URL`, `GROQ_API_KEY`. Loaded via `config.py` which also defines all URL patterns, paths, and CSS selectors.

## Architecture

**Pipeline flow:** `main.py` orchestrates two modes:

1. **Monitor mode** (default): login → scrape → diff against saved state → notify Discord → save state
2. **Analyze mode** (`--analyze`): login → scrape → download files → extract text → send to Groq LLM → save markdown report

**Module responsibilities:**

- `login.py` — Playwright browser auth with Google OAuth. Saves/restores session cookies to `data/browser_state.json` for headless reuse.
- `scraper.py` — Four async scrapers: `scrape_courses`, `scrape_assignments` (dashboard timeline), `scrape_grades` (overview table), `scrape_materials` (per-course page sections). All return dataclass instances from `models.py`.
- `models.py` — `Assignment`, `Grade`, `Material` dataclasses. Each has a `.key` property used for state diffing.
- `differ.py` — JSON state persistence (`data/state.json`). `build_state` creates key→dict maps; `compute_changes` diffs old vs new to produce a `Changes` object tracking new assignments/grades/materials, grade updates, and upcoming deadlines (48h window).
- `notifier.py` — Formats `Changes` into Discord markdown and sends via webhook. Handles message splitting at 2000-char limit.
- `downloader.py` — Downloads file-type materials using Playwright's download API. Saves to `data/downloads/<course_name>/`. Skips already-downloaded files.
- `extractor.py` — Text extraction from PDF (pdfplumber) and PPTX (python-pptx). Returns `{filename: text}` dict.
- `analyzer.py` — Sends extracted text + grades + assignments to Groq (`llama-3.3-70b-versatile`). Prioritizes slides over PDFs when truncating to fit context limits (28k chars total, 8k per file). Saves analysis to `data/analyses/`.

**Data directory structure:** `data/state.json` (scrape state), `data/browser_state.json` (Playwright session), `data/downloads/` (course files), `data/analyses/` (AI reports).

## Key Patterns

- All scraping is async (Playwright). The browser context is shared across all scrape functions within a single run.
- Moodle CSS selectors are hardcoded in `scraper.py` and `config.py` — these are fragile and tied to the specific Moodle instance's theme.
- Course tuples are `(course_id, course_name, course_url)` passed around as `list[tuple[str, str, str]]`.
- No test suite exists.
