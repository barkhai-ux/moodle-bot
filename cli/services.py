import logging
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

from playwright.async_api import async_playwright

from cli.config import DATA_DIR, STORAGE_STATE
from cli.differ import build_state, compute_changes, load_state, save_state
from cli.login import get_authenticated_context
from cli.models import to_dict
from cli.notifier import send_notification
from cli.scraper import scrape_assignments, scrape_courses, scrape_grades, scrape_materials

log = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class SnapshotResult:
    assignments: list[Any]
    grades: list[Any]


@dataclass
class MonitorResult:
    changes_summary: str
    changes: Any
    assignments_count: int
    grades_count: int
    materials_count: int


def select_courses(
    courses: list[tuple[str, str, str]],
    selectors: list[str] | None,
) -> list[tuple[str, str, str]]:
    """Select courses by exact ID or substring match on course name."""
    if not selectors:
        return courses

    lowered = [s.strip().lower() for s in selectors if s.strip()]
    if not lowered:
        return courses

    selected: list[tuple[str, str, str]] = []
    for cid, name, url in courses:
        name_l = name.lower()
        if any(sel == cid or sel in name_l for sel in lowered):
            selected.append((cid, name, url))

    return selected or courses


async def collect_baseline(page, verbose: bool = False):
    courses = await scrape_courses(page)
    if verbose:
        print(f"\nCourses ({len(courses)}):")
        for cid, name, _ in courses:
            print(f"  [{cid}] {name}")

    assignments = await scrape_assignments(page)
    if verbose:
        print(f"\nAssignments ({len(assignments)}):")
        for a in assignments:
            print(f"  [{a.course_name}] {a.title} - Due: {a.due_date} - {a.status}")

    grades = await scrape_grades(page, courses)
    if verbose:
        print(f"\nGrades ({len(grades)}):")
        for g in grades:
            print(f"  [{g.course_name}] {g.grade}")

    return courses, assignments, grades


async def run_snapshot(
    page,
    include_assignments: bool,
    include_grades: bool,
    verbose: bool = False,
) -> SnapshotResult:
    log.info(
        "Running snapshot include_assignments=%s include_grades=%s",
        include_assignments,
        include_grades,
    )
    assignments = await scrape_assignments(page) if include_assignments else []
    grades = []

    if include_grades:
        grades = await scrape_grades(page)

    if verbose and assignments:
        print(f"\nAssignments ({len(assignments)}):")
        for a in assignments:
            print(f"  [{a.course_name}] {a.title} - Due: {a.due_date} - {a.status}")

    if verbose and grades:
        print(f"\nGrades ({len(grades)}):")
        for g in grades:
            print(f"  [{g.course_name}] {g.grade}")

    return SnapshotResult(assignments=assignments, grades=grades)


async def run_monitor_mode(
    page,
    verbose: bool = False,
    dry_run: bool = False,
    first_run: bool = False,
    notify: bool = True,
) -> MonitorResult:
    courses, assignments, grades = await collect_baseline(page, verbose=verbose)
    materials = await scrape_materials(page, courses)

    if verbose:
        print(f"\nMaterials ({len(materials)}):")
        for m in materials:
            print(f"  [{m.course_name}] {m.title} ({m.resource_type})")

    new_state = build_state(assignments, grades, materials)
    old_state = load_state()
    changes = compute_changes(old_state, new_state)

    if notify and not first_run and not dry_run:
        send_notification(changes)
    elif first_run:
        print("First run - skipping notifications, saving initial state.")
    elif dry_run:
        print("Dry run - skipping notifications.")

    save_state(new_state)

    return MonitorResult(
        changes_summary=changes.summary(),
        changes=changes,
        assignments_count=len(assignments),
        grades_count=len(grades),
        materials_count=len(materials),
    )


async def run_analyze(
    page,
    selectors: list[str] | None = None,
) -> list[Path]:
    from cli.analyzer import analyze_course
    from cli.downloader import download_course_materials
    from cli.extractor import extract_all

    courses, assignments, grades = await collect_baseline(page, verbose=False)
    selected = select_courses(courses, selectors)

    materials = await scrape_materials(page, selected)

    by_course: dict[str, list[dict]] = {}
    for m in materials:
        by_course.setdefault(m.course_name, []).append(to_dict(m))

    assign_dicts = [to_dict(a) for a in assignments]
    grade_dicts = [to_dict(g) for g in grades]

    output_files: list[Path] = []
    analysis_dir = DATA_DIR / "analyses"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    for _, cname, _ in selected:
        course_materials = by_course.get(cname, [])
        file_materials = [m for m in course_materials if m.get("resource_type") == "file"]
        if not file_materials:
            continue

        downloaded = await download_course_materials(page, file_materials, cname)
        if not downloaded:
            continue

        texts = extract_all(downloaded)
        if not texts:
            continue

        analysis = analyze_course(cname, texts, grade_dicts, assign_dicts)
        safe_name = cname.replace(" ", "_").replace("/", "_")
        analysis_file = analysis_dir / f"{safe_name}_analysis.md"
        analysis_file.write_text(f"# Learning Recommendations: {cname}\n\n{analysis}")
        output_files.append(analysis_file)

    return output_files


async def run_analyze_all(
    page,
    selectors: list[str] | None = None,
) -> Path | None:
    from cli.analyzer import analyze_all_courses
    from cli.downloader import download_course_materials
    from cli.extractor import extract_all

    courses, assignments, grades = await collect_baseline(page, verbose=False)
    selected = select_courses(courses, selectors)

    materials = await scrape_materials(page, selected)
    by_course: dict[str, list[dict]] = {}
    for m in materials:
        by_course.setdefault(m.course_name, []).append(to_dict(m))

    assign_dicts = [to_dict(a) for a in assignments]
    grade_dicts = [to_dict(g) for g in grades]

    all_materials: dict[str, dict[str, str]] = {}
    for _, cname, _ in selected:
        course_materials = by_course.get(cname, [])
        file_materials = [m for m in course_materials if m.get("resource_type") == "file"]
        if not file_materials:
            continue

        downloaded = await download_course_materials(page, file_materials, cname)
        if not downloaded:
            continue

        texts = extract_all(downloaded)
        if texts:
            all_materials[cname] = texts

    if not all_materials:
        return None

    analysis = analyze_all_courses(all_materials, grade_dicts, assign_dicts)
    analysis_dir = DATA_DIR / "analyses"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    analysis_file = analysis_dir / "all_courses_analysis.md"
    analysis_file.write_text(f"# Unified Study Plan - All Courses\n\n{analysis}")
    return analysis_file


async def run_authenticated(
    action: Callable[[Any], Awaitable[T]],
    headed: bool = False,
    force_login: bool = False,
    allow_interactive_login: bool = True,
) -> T:
    log.info(
        "Opening authenticated browser context headed=%s force_login=%s interactive_login=%s",
        headed,
        force_login,
        allow_interactive_login,
    )
    log.info("Starting Playwright driver...")
    pw = await asyncio.wait_for(async_playwright().start(), timeout=20)
    log.info("Playwright driver started.")
    try:
        if force_login:
            STORAGE_STATE.unlink(missing_ok=True)
            headed = True

        browser, context, page = await get_authenticated_context(
            pw,
            headed=headed,
            allow_interactive_login=allow_interactive_login,
        )
        try:
            result = await action(page)
            log.info("Authenticated action completed successfully.")
            return result
        finally:
            await context.close()
            await browser.close()
    finally:
        await pw.stop()
        log.info("Playwright driver stopped.")
