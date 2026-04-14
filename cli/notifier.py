import logging
from discord_webhook import DiscordWebhook

from cli.config import DISCORD_WEBHOOK_URL
from cli.differ import Changes

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
        ordered_items = sorted(
            grouped[course],
            key=lambda item: (
                item.get("due_date", "") or "",
                item.get("title", "") or "",
                item.get("grade", "") or "",
            ),
        )
        for item in ordered_items:
            for row in render_item(item):
                if row:
                    lines.append(row)
        lines.append("")


def _collapse_blank_lines(lines: list[str]) -> list[str]:
    cleaned = []
    for line in lines:
        if line == "" and cleaned and cleaned[-1] == "":
            continue
        cleaned.append(line)
    return cleaned


def format_message(changes: Changes) -> str:
    """Format changes into a readable notification message."""
    lines = ["**📋 MOODLE UPDATE**", ""]

    if not changes.has_any():
        lines.append("No changes detected.")
        return "\n".join(lines)

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

    return "\n".join(_collapse_blank_lines(lines)).strip()


def send_discord(message: str) -> bool:
    """Send a message to Discord via webhook. Splits if over 2000 chars."""
    if not DISCORD_WEBHOOK_URL:
        log.warning("DISCORD_WEBHOOK_URL not set, skipping notification.")
        return False

    if not message.strip():
        log.info("Empty Discord message, skipping send.")
        return False

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

    sent_any = False
    for chunk in chunks:
        webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL, content=chunk)
        response = webhook.execute()
        if response and hasattr(response, "status_code") and response.status_code >= 400:
            log.error("Discord webhook failed: %s", response.status_code)
            continue
        sent_any = True
    return sent_any


def send_assignments(assignments) -> bool:
    """Format and send all current assignments to Discord."""
    if not assignments:
        log.info("No assignments to send.")
        return False

    lines = ["**📋 ALL ASSIGNMENTS**", ""]
    assignment_dicts = [
        {
            "course_name": a.course_name,
            "title": a.title,
            "due_date": a.due_date,
            "status": a.status,
            "url": a.url,
        }
        for a in assignments
    ]
    grouped = _group_by_course(assignment_dicts)
    for course in sorted(grouped):
        lines.append(f"**{course}**")
        for a in grouped[course]:
            lines.append(f"  • **{a['title']}**")
            lines.append(f"    Due: {a.get('due_date') or 'N/A'} — {a.get('status', 'N/A')}")
            if a.get("url"):
                lines.append(f"    {a['url']}")
        lines.append("")

    message = "\n".join(lines).strip()
    log.info("Sending assignments to Discord...")
    sent = send_discord(message)
    if sent:
        log.info("Assignments sent.")
    else:
        log.info("Assignments not sent.")
    return sent


def send_grades(grades) -> bool:
    """Format and send all current grades to Discord."""
    filtered_grades = [g for g in grades if getattr(g, "course_name", "").strip()]

    if not filtered_grades:
        log.info("No grades to send.")
        return False

    lines = ["**📊 ALL GRADES**", ""]
    grade_dicts = [
        {
            "course_name": g.course_name,
            "grade": g.grade,
            "url": g.url,
        }
        for g in filtered_grades
    ]
    grouped = _group_by_course(grade_dicts)
    for course in sorted(grouped):
        lines.append(f"**{course}**")
        for g in grouped[course]:
            lines.append(f"  • **{g.get('grade', 'N/A')}**")
            if g.get("url"):
                lines.append(f"    {g['url']}")
        lines.append("")

    message = "\n".join(lines).strip()
    log.info("Sending grades to Discord...")
    sent = send_discord(message)
    if sent:
        log.info("Grades sent.")
    else:
        log.info("Grades not sent.")
    return sent


def send_notification(changes: Changes):
    """Format and send a Discord notification for the latest run."""
    message = format_message(changes)

    log.info("Sending Discord notification...")
    sent = send_discord(message)
    if sent:
        log.info("Notification sent.")
    else:
        log.info("Notification was not sent.")
