import logging
from discord_webhook import DiscordWebhook

from config import DISCORD_WEBHOOK_URL
from differ import Changes

log = logging.getLogger(__name__)

MAX_DISCORD_LENGTH = 2000  # Discord message character limit


def _group_by_course(items, course_key: str = "course_name") -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for item in items:
        course = item.get(course_key, "Unknown course")
        grouped.setdefault(course, []).append(item)
    return grouped


def _append_grouped_items(lines: list[str], items: list[dict], render_item):
    grouped = _group_by_course(items)
    for course in sorted(grouped):
        lines.append(f"**{course}**")
        for item in grouped[course]:
            for row in render_item(item):
                if row:
                    lines.append(row)
        lines.append("")


def format_message(changes: Changes) -> str:
    """Format changes into a readable notification message."""
    if not changes.has_any():
        return ""

    lines = ["**📋 MOODLE UPDATE**", ""]

    if changes.upcoming_deadlines:
        lines.append(f"**⏰ UPCOMING DEADLINES ({len(changes.upcoming_deadlines)})**")
        _append_grouped_items(
            lines,
            changes.upcoming_deadlines,
            lambda a: [
                f"  • **{a['title']}**",
                f"    Due: {a.get('due_date', 'N/A')}",
                f"    {a['url']}" if a.get("url") else None,
            ],
        )

    if changes.new_assignments:
        lines.append(f"**📝 NEW ASSIGNMENTS ({len(changes.new_assignments)})**")
        _append_grouped_items(
            lines,
            changes.new_assignments,
            lambda a: [
                f"  • **{a['title']}**",
                f"    Due: {a.get('due_date', 'N/A')}",
                f"    {a['url']}" if a.get("url") else None,
            ],
        )

    if changes.grade_updates:
        lines.append(f"**📊 GRADE UPDATES ({len(changes.grade_updates)})**")
        grade_updates = [
            {
                "old": old,
                "new": new,
                "course_name": new.get("course_name", "Unknown course"),
            }
            for old, new in changes.grade_updates
        ]
        _append_grouped_items(
            lines,
            grade_updates,
            lambda u: [
                f"  • {u['old'].get('grade', '?')} → **{u['new'].get('grade', '?')}**",
                f"    {u['new']['url']}" if u["new"].get("url") else None,
            ],
        )

    if changes.new_grades:
        lines.append(f"**📊 NEW GRADES ({len(changes.new_grades)})**")
        _append_grouped_items(
            lines,
            changes.new_grades,
            lambda g: [
                f"  • **{g.get('grade', '-')}**",
                f"    {g['url']}" if g.get("url") else None,
            ],
        )

    if changes.new_materials:
        lines.append(f"**📂 NEW MATERIALS ({len(changes.new_materials)})**")
        _append_grouped_items(
            lines,
            changes.new_materials,
            lambda m: [f"  • {m['title']} ({m.get('resource_type', '?')})"],
        )

    cleaned = []
    for line in lines:
        if line == "" and cleaned and cleaned[-1] == "":
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def send_discord(message: str):
    """Send a message to Discord via webhook. Splits if over 2000 chars."""
    if not DISCORD_WEBHOOK_URL:
        log.warning("DISCORD_WEBHOOK_URL not set, skipping notification.")
        return

    # Split long messages
    chunks = []
    while len(message) > MAX_DISCORD_LENGTH:
        # Find a good split point (newline)
        split_at = message.rfind("\n", 0, MAX_DISCORD_LENGTH)
        if split_at == -1:
            split_at = MAX_DISCORD_LENGTH
        chunks.append(message[:split_at])
        message = message[split_at:].lstrip("\n")
    if message:
        chunks.append(message)

    for chunk in chunks:
        webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL, content=chunk)
        response = webhook.execute()
        if response and hasattr(response, "status_code") and response.status_code >= 400:
            log.error("Discord webhook failed: %s", response.status_code)


def send_assignments(assignments):
    """Format and send all current assignments to Discord."""
    if not assignments:
        log.info("No assignments to send.")
        return

    lines = ["**📋 ALL ASSIGNMENTS**", ""]
    for a in assignments:
        lines.append(f"  [{a.course_name}] **{a.title}**")
        lines.append(f"    Due: {a.due_date or 'N/A'} — {a.status}")
        if a.url:
            lines.append(f"    {a.url}")
    lines.append("")

    message = "\n".join(lines)
    log.info("Sending assignments to Discord...")
    send_discord(message)
    log.info("Assignments sent.")


def send_grades(grades):
    """Format and send all current grades to Discord."""
    if not grades:
        log.info("No grades to send.")
        return

    lines = ["**📊 ALL GRADES**", ""]
    for g in grades:
        lines.append(f"  [{g.course_name}] **{g.grade}**")
        if g.url:
            lines.append(f"    {g.url}")
    lines.append("")

    message = "\n".join(lines)
    log.info("Sending grades to Discord...")
    send_discord(message)
    log.info("Grades sent.")


def send_notification(changes: Changes):
    """Format and send notification for detected changes."""
    message = format_message(changes)
    if not message:
        log.info("No changes to notify.")
        return

    log.info("Sending Discord notification...")
    send_discord(message)
    log.info("Notification sent.")
