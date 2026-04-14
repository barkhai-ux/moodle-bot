import logging
from playwright.async_api import Playwright

from cli.config import DASHBOARD_URL, LOGIN_URL, STORAGE_STATE

log = logging.getLogger(__name__)

# How long to wait for the user to complete Google OAuth (5 minutes)
MANUAL_LOGIN_TIMEOUT = 300_000


async def get_authenticated_context(
    pw: Playwright,
    headed: bool = False,
    allow_interactive_login: bool = True,
):
    """Return (browser, context, page) with an authenticated Moodle session.

    Uses saved session cookies when available. If the session is expired
    or missing, opens a headed browser for manual Google OAuth login,
    then saves the session for future headless runs.
    """
    browser = await pw.chromium.launch(headless=not headed)

    # Try restoring a saved session
    if STORAGE_STATE.exists():
        log.info("Restoring saved session...")
        context = await browser.new_context(storage_state=str(STORAGE_STATE))
        page = await context.new_page()
        await page.goto(DASHBOARD_URL, timeout=30000)

        if "/login/" not in page.url and "accounts.google.com" not in page.url:
            log.info("Session still valid.")
            return browser, context, page

        log.info("Session expired.")
        await context.close()

    # No valid session — need manual Google login
    if not allow_interactive_login:
        await browser.close()
        raise RuntimeError(
            "Saved Moodle session is missing or expired. Run /login_refresh to sign in again."
        )

    # Must be headed so the user can interact with Google OAuth
    if not headed:
        await browser.close()
        log.info("No valid session. Relaunching in headed mode for Google login...")
        browser = await pw.chromium.launch(headless=False)

    context = await browser.new_context()
    page = await context.new_page()

    log.info("Navigating to Moodle login page...")
    await page.goto(LOGIN_URL, timeout=30000)

    print("\n" + "=" * 60)
    print("  GOOGLE LOGIN REQUIRED")
    print("  Please complete the Google sign-in in the browser window.")
    print("  The bot will continue automatically once you're logged in.")
    print("=" * 60 + "\n")

    # Wait for the user to complete OAuth and land on the dashboard
    try:
        await page.wait_for_url(
            f"**{DASHBOARD_URL.split('://', 1)[-1]}**",
            timeout=MANUAL_LOGIN_TIMEOUT,
        )
    except Exception:
        # Also check if we ended up on any Moodle page (not login/google)
        if "/login/" in page.url or "accounts.google.com" in page.url:
            STORAGE_STATE.unlink(missing_ok=True)
            await browser.close()
            raise RuntimeError(
                "Login timed out or failed. Run again with --headed and complete Google sign-in."
            )

    # Save session for future headless runs
    STORAGE_STATE.parent.mkdir(parents=True, exist_ok=True)
    await context.storage_state(path=str(STORAGE_STATE))
    log.info("Login successful, session saved for future runs.")

    return browser, context, page
