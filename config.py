import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Moodle
BASE_URL = os.getenv("MOODLE_URL", "https://online.aum.edu.mn").rstrip("/")

# Discord
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Groq
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Paths
PROJECT_DIR = Path(__file__).parent
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
