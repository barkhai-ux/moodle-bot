import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

# Moodle
BASE_URL = os.getenv("MOODLE_URL", "https://online.aum.edu.mn").rstrip("/")

# Discord
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")


def _parse_int_set(value: str) -> set[int]:
    out: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return out


DISCORD_ALLOWED_USER_IDS = _parse_int_set(os.getenv("DISCORD_ALLOWED_USER_IDS", ""))
DISCORD_ALLOWED_ROLE_IDS = _parse_int_set(os.getenv("DISCORD_ALLOWED_ROLE_IDS", ""))

_guild = os.getenv("DISCORD_CONTROL_GUILD_ID", "").strip()
DISCORD_CONTROL_GUILD_ID = int(_guild) if _guild.isdigit() else None

# Groq
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Paths
DATA_DIR = PROJECT_DIR / "data"
DOWNLOADS_DIR = DATA_DIR / "downloads"
STATE_FILE = DATA_DIR / "state.json"
STORAGE_STATE = DATA_DIR / "browser_state.json"

# Moodle URL patterns
LOGIN_URL = f"{BASE_URL}/login/index.php"
DASHBOARD_URL = f"{BASE_URL}/my/"
GRADES_OVERVIEW_URL = f"{BASE_URL}/grade/report/overview/index.php"

def assign_index_url(course_id):
    return f"{BASE_URL}/mod/assign/index.php?id={course_id}"

def course_url(course_id):
    return f"{BASE_URL}/course/view.php?id={course_id}"

# Selectors
SEL_COURSE_LINK = "a[href*='course/view.php']"
