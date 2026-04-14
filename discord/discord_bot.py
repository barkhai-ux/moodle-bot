import asyncio
import logging
import sys
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from cli.config import (
    DISCORD_ALLOWED_ROLE_IDS,
    DISCORD_ALLOWED_USER_IDS,
    DISCORD_BOT_TOKEN,
    DISCORD_CONTROL_GUILD_ID,
)
from cli.differ import load_state
from cli.notifier import format_message
from cli.services import (
    run_analyze,
    run_analyze_all,
    run_authenticated,
    run_monitor_mode,
    run_snapshot,
)

log = logging.getLogger(__name__)
MAX_MESSAGE = 1900
COMMAND_TIMEOUT_SECONDS = 120


def split_text(text: str, max_len: int = MAX_MESSAGE) -> list[str]:
    if len(text) <= max_len:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > max_len:
        split_at = remaining.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


def is_authorized(interaction: discord.Interaction) -> bool:
    if not DISCORD_ALLOWED_USER_IDS and not DISCORD_ALLOWED_ROLE_IDS:
        return True

    if interaction.user and interaction.user.id in DISCORD_ALLOWED_USER_IDS:
        return True

    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    if member is None:
        return False

    role_ids = {role.id for role in member.roles}
    return bool(role_ids.intersection(DISCORD_ALLOWED_ROLE_IDS))


class MoodleControlBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.run_lock = asyncio.Lock()

    async def setup_hook(self):
        if DISCORD_CONTROL_GUILD_ID:
            guild = discord.Object(id=DISCORD_CONTROL_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced slash commands to guild %s", DISCORD_CONTROL_GUILD_ID)
        else:
            await self.tree.sync()
            log.info("Synced global slash commands")

    async def on_ready(self):
        user = self.user
        log.info("Bot ready as %s (%s); connected guilds: %s", user, getattr(user, "id", "?"), len(self.guilds))


bot = MoodleControlBot()


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # Always surface command failures to users instead of failing silently.
    log.exception("Slash command error for user=%s command=%s", getattr(interaction.user, "id", "?"), getattr(interaction.command, "name", "unknown"), exc_info=error)
    message = f"Command failed: {error}"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except Exception:
        log.exception("Failed to send command error response")


async def guarded_run(
    interaction: discord.Interaction,
    title: str,
    runner,
):
    if not is_authorized(interaction):
        await interaction.response.send_message("Not authorized for this command.", ephemeral=True)
        return

    if bot.run_lock.locked():
        await interaction.response.send_message(
            "Another job is running. Try again when it finishes.",
            ephemeral=True,
        )
        return

    log.info("Starting command: %s", title)
    await interaction.response.defer(thinking=True)

    async with bot.run_lock:
        try:
            result = await asyncio.wait_for(runner(), timeout=COMMAND_TIMEOUT_SECONDS)
            log.info("Finished command: %s", title)
        except asyncio.TimeoutError:
            log.warning("Command timed out: %s", title)
            await interaction.followup.send(
                f"{title} timed out after {COMMAND_TIMEOUT_SECONDS} seconds.",
            )
            return
        except Exception as exc:
            log.exception("Command failed: %s", title)
            await interaction.followup.send(f"{title} failed: {exc}")
            return

    if isinstance(result, str):
        for chunk in split_text(result):
            await interaction.followup.send(chunk)
    else:
        await interaction.followup.send(f"{title} complete.")


@bot.tree.command(name="ping", description="Check if the Moodle control bot is alive")
async def ping(interaction: discord.Interaction):
    log.info("/ping invoked by user=%s guild=%s", getattr(interaction.user, "id", "?"), getattr(interaction.guild, "id", "DM"))
    await interaction.response.send_message("Pong. Moodle control bot is running.", ephemeral=True)


@bot.tree.command(name="status", description="Show bot state and last monitor run time")
async def status(interaction: discord.Interaction):
    log.info("/status invoked by user=%s guild=%s", getattr(interaction.user, "id", "?"), getattr(interaction.guild, "id", "DM"))
    if not is_authorized(interaction):
        await interaction.response.send_message("Not authorized for this command.", ephemeral=True)
        return

    state = load_state()
    last_run = state.get("last_run", "Never")
    lock_state = "busy" if bot.run_lock.locked() else "idle"
    await interaction.response.send_message(
        f"Run lock: {lock_state}\nLast monitor run: {last_run}",
        ephemeral=True,
    )


@bot.tree.command(name="monitor_now", description="Run full monitor cycle immediately")
async def monitor_now(interaction: discord.Interaction):
    log.info("/monitor_now invoked by user=%s guild=%s", getattr(interaction.user, "id", "?"), getattr(interaction.guild, "id", "DM"))
    async def _runner():
        async def _action(page):
            return await run_monitor_mode(page, notify=True)

        result = await run_authenticated(_action, allow_interactive_login=False)
        message = format_message(result.changes)
        return f"Monitor completed. Summary: {result.changes_summary}\n\n{message}"

    await guarded_run(interaction, "Monitor", _runner)


@bot.tree.command(name="assignments_now", description="Fetch and print current assignments")
async def assignments_now(interaction: discord.Interaction):
    log.info("/assignments_now invoked by user=%s guild=%s", getattr(interaction.user, "id", "?"), getattr(interaction.guild, "id", "DM"))
    async def _runner():
        async def _action(page):
            return await run_snapshot(page, include_assignments=True, include_grades=False)

        snapshot = await run_authenticated(_action, allow_interactive_login=False)
        if not snapshot.assignments:
            return "No assignments found."

        lines = [f"Assignments: {len(snapshot.assignments)}", ""]
        for a in snapshot.assignments:
            lines.append(f"- [{a.course_name}] {a.title}")
            lines.append(f"  Due: {a.due_date or 'N/A'}")
        return "\n".join(lines)

    await guarded_run(interaction, "Assignments", _runner)


@bot.tree.command(name="grades_now", description="Fetch and print current grades")
async def grades_now(interaction: discord.Interaction):
    log.info("/grades_now invoked by user=%s guild=%s", getattr(interaction.user, "id", "?"), getattr(interaction.guild, "id", "DM"))
    async def _runner():
        async def _action(page):
            return await run_snapshot(page, include_assignments=False, include_grades=True)

        snapshot = await run_authenticated(_action, allow_interactive_login=False)
        grades = [g for g in snapshot.grades if g.course_name.strip()]

        if not grades:
            return "No grades found."

        lines = [f"Grades: {len(grades)}", ""]
        for g in grades:
            lines.append(f"- [{g.course_name}] {g.grade}")
        return "\n".join(lines)

    await guarded_run(interaction, "Grades", _runner)


@bot.tree.command(name="analyze", description="Analyze one course (or all if omitted)")
@app_commands.describe(course="Course ID or a name substring")
async def analyze(interaction: discord.Interaction, course: str | None = None):
    log.info("/analyze invoked by user=%s guild=%s course=%s", getattr(interaction.user, "id", "?"), getattr(interaction.guild, "id", "DM"), course)
    async def _runner():
        selectors = [course] if course else None

        async def _action(page):
            return await run_analyze(page, selectors=selectors)

        files = await run_authenticated(_action, allow_interactive_login=False)
        if not files:
            return "No analysis files were generated."

        names = "\n".join(f"- {Path(p).name}" for p in files)
        return f"Generated {len(files)} analysis file(s):\n{names}"

    await guarded_run(interaction, "Analyze", _runner)


@bot.tree.command(name="analyze_all", description="Run one unified analysis across selected/all courses")
@app_commands.describe(course_filter="Optional course ID or name substring")
async def analyze_all(interaction: discord.Interaction, course_filter: str | None = None):
    log.info("/analyze_all invoked by user=%s guild=%s course_filter=%s", getattr(interaction.user, "id", "?"), getattr(interaction.guild, "id", "DM"), course_filter)
    async def _runner():
        selectors = [course_filter] if course_filter else None

        async def _action(page):
            return await run_analyze_all(page, selectors=selectors)

        path = await run_authenticated(_action, allow_interactive_login=False)
        if not path:
            return "No unified analysis generated (no extractable materials found)."
        return f"Unified analysis generated: {Path(path).name}"

    await guarded_run(interaction, "Analyze all", _runner)


@bot.tree.command(name="login_refresh", description="Force Moodle re-login flow and refresh session")
async def login_refresh(interaction: discord.Interaction):
    log.info("/login_refresh invoked by user=%s guild=%s", getattr(interaction.user, "id", "?"), getattr(interaction.guild, "id", "DM"))
    async def _runner():
        async def _action(page):
            return page.url

        await run_authenticated(_action, headed=True, force_login=True)
        return "Session refresh complete."

    await guarded_run(interaction, "Login refresh", _runner)


def main():
    if not DISCORD_BOT_TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN is not set in .env")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()
