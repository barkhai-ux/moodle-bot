import argparse
import asyncio
import logging
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from login import get_authenticated_context
from scraper import scrape_courses, scrape_assignments, scrape_grades, scrape_materials
from differ import load_state, save_state, build_state, compute_changes
from notifier import send_notification, send_assignments, send_grades
from models import to_dict


def parse_args():
    parser = argparse.ArgumentParser(description="Moodle Scraper Bot")
    parser.add_argument("--headed", action="store_true", help="Show browser window")
    parser.add_argument("--verbose", action="store_true", help="Print scraped data")
    parser.add_argument("--dry-run", action="store_true", help="Scrape but don't notify")
    parser.add_argument("--first-run", action="store_true",
                        help="Save initial state without sending notifications")
    parser.add_argument("--login", action="store_true",
                        help="Force re-login (opens browser for Google OAuth)")
    parser.add_argument("--assignments", action="store_true",
                        help="Send current assignment list to Discord")
    parser.add_argument("--grades", action="store_true",
                        help="Send current grades to Discord")
    parser.add_argument("--analyze", action="store_true",
                        help="Download materials and generate AI learning recommendations")
    parser.add_argument("--analyze-all", action="store_true",
                        help="Analyze all selected courses together in one unified study plan")
    return parser.parse_args()


def pick_courses(courses: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Interactive course selection for analysis."""
    print("\nAvailable courses:")
    for i, (cid, name, url) in enumerate(courses, 1):
        print(f"  {i}. {name}")
    print(f"  0. All courses")

    choice = input("\nEnter course numbers (comma-separated, e.g. 1,3,5): ").strip()

    if choice == "0":
        return courses

    selected = []
    for part in choice.split(","):
        try:
            idx = int(part.strip()) - 1
            if 0 <= idx < len(courses):
                selected.append(courses[idx])
        except ValueError:
            continue

    if not selected:
        print("No valid selection, using all courses.")
        return courses

    print(f"\nSelected: {', '.join(name for _, name, _ in selected)}")
    return selected


async def run_analyze(page, courses, assignments, grades):
    """Download materials, extract text, and run AI analysis."""
    from downloader import download_course_materials
    from extractor import extract_all
    from analyzer import analyze_course
    from config import DOWNLOADS_DIR, DATA_DIR

    selected = pick_courses(courses)

    # First scrape materials for selected courses only
    print("\nScraping materials for selected courses...")
    materials = await scrape_materials(page, selected)

    # Group materials by course
    by_course = {}
    for m in materials:
        cname = m.course_name
        if cname not in by_course:
            by_course[cname] = []
        by_course[cname].append(to_dict(m))

    # Convert assignments and grades to dicts
    assign_dicts = [to_dict(a) for a in assignments]
    grade_dicts = [to_dict(g) for g in grades]

    for _, cname, _ in selected:
        print(f"\n{'=' * 60}")
        print(f"  Analyzing: {cname}")
        print(f"{'=' * 60}")

        course_materials = by_course.get(cname, [])
        file_materials = [m for m in course_materials if m.get("resource_type") == "file"]

        if not file_materials:
            print(f"  No downloadable files found for {cname}.")
            continue

        print(f"  Found {len(file_materials)} downloadable files.")

        # Download
        downloaded = await download_course_materials(page, file_materials, cname)

        if not downloaded:
            print(f"  No files downloaded for {cname}.")
            continue

        print(f"  Extracting text from {len(downloaded)} files...")
        texts = extract_all(downloaded)

        if not texts:
            print(f"  Could not extract text from any files in {cname}.")
            continue

        # Analyze with AI
        print(f"  Generating AI analysis ({len(texts)} files, sending to Groq)...")
        try:
            analysis = analyze_course(cname, texts, grade_dicts, assign_dicts)
        except Exception as e:
            import traceback
            print(f"  AI analysis failed: {e}")
            traceback.print_exc()
            continue

        # Save analysis to file
        analysis_dir = DATA_DIR / "analyses"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        safe_name = cname.replace(" ", "_").replace("/", "_")
        analysis_file = analysis_dir / f"{safe_name}_analysis.md"
        analysis_file.write_text(f"# Learning Recommendations: {cname}\n\n{analysis}")

        # Print to terminal
        print(f"\n{analysis}")
        print(f"\n  Saved to: {analysis_file}")


async def run_analyze_all(page, courses, assignments, grades):
    """Download materials from all selected courses and analyze them together."""
    from downloader import download_course_materials
    from extractor import extract_all
    from analyzer import analyze_all_courses
    from config import DATA_DIR

    selected = pick_courses(courses)

    print("\nScraping materials for selected courses...")
    materials = await scrape_materials(page, selected)

    # Group materials by course
    by_course = {}
    for m in materials:
        cname = m.course_name
        if cname not in by_course:
            by_course[cname] = []
        by_course[cname].append(to_dict(m))

    assign_dicts = [to_dict(a) for a in assignments]
    grade_dicts = [to_dict(g) for g in grades]

    # Download and extract for each course
    all_materials = {}  # {course_name: {filename: text}}
    for _, cname, _ in selected:
        print(f"\n  Processing: {cname}")

        course_materials = by_course.get(cname, [])
        file_materials = [m for m in course_materials if m.get("resource_type") == "file"]

        if not file_materials:
            print(f"    No downloadable files found.")
            continue

        downloaded = await download_course_materials(page, file_materials, cname)
        if not downloaded:
            print(f"    No files downloaded.")
            continue

        print(f"    Extracting text from {len(downloaded)} files...")
        texts = extract_all(downloaded)
        if texts:
            all_materials[cname] = texts
            print(f"    Got text from {len(texts)} files.")
        else:
            print(f"    Could not extract text from any files.")

    if not all_materials:
        print("\nNo materials extracted from any course. Nothing to analyze.")
        return

    print(f"\n{'=' * 60}")
    print(f"  Generating unified analysis ({len(all_materials)} courses, sending to Groq)...")
    print(f"{'=' * 60}")

    try:
        analysis = analyze_all_courses(all_materials, grade_dicts, assign_dicts)
    except Exception as e:
        import traceback
        print(f"  AI analysis failed: {e}")
        traceback.print_exc()
        return

    # Save
    analysis_dir = DATA_DIR / "analyses"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    analysis_file = analysis_dir / "all_courses_analysis.md"
    analysis_file.write_text(f"# Unified Study Plan — All Courses\n\n{analysis}")

    print(f"\n{analysis}")
    print(f"\n  Saved to: {analysis_file}")


async def run(args):
    async with async_playwright() as pw:
        # Force re-login by deleting saved session
        if args.login:
            from config import STORAGE_STATE
            STORAGE_STATE.unlink(missing_ok=True)
            args.headed = True  # Must be headed for Google OAuth

        browser, context, page = await get_authenticated_context(pw, headed=args.headed)

        try:
            # Scrape courses and assignments (always needed)
            courses = await scrape_courses(page)
            if args.verbose:
                print(f"\nCourses ({len(courses)}):")
                for cid, name, url in courses:
                    print(f"  [{cid}] {name}")

            assignments = await scrape_assignments(page)
            if args.verbose:
                print(f"\nAssignments ({len(assignments)}):")
                for a in assignments:
                    print(f"  [{a.course_name}] {a.title} — Due: {a.due_date} — {a.status}")

            grades = await scrape_grades(page, courses)
            if args.verbose:
                print(f"\nGrades ({len(grades)}):")
                for g in grades:
                    print(f"  [{g.course_name}] {g.grade}")

            # On-demand Discord sends
            if args.assignments:
                send_assignments(assignments)
            if args.grades:
                send_grades(grades)
            if args.assignments or args.grades:
                return

            # Analyze mode: download + extract + AI recommendations
            if args.analyze_all:
                await run_analyze_all(page, courses, assignments, grades)
            elif args.analyze:
                await run_analyze(page, courses, assignments, grades)
            else:
                # Normal scrape mode
                materials = await scrape_materials(page, courses)
                if args.verbose:
                    print(f"\nMaterials ({len(materials)}):")
                    for m in materials:
                        print(f"  [{m.course_name}] {m.title} ({m.resource_type})")

                # Diff
                new_state = build_state(assignments, grades, materials)
                old_state = load_state()
                changes = compute_changes(old_state, new_state)

                print(f"\nChanges: {changes.summary()}")

                # Notify
                if changes.has_any() and not args.first_run and not args.dry_run:
                    send_notification(changes)
                elif args.first_run:
                    print("First run — skipping notifications, saving initial state.")
                elif args.dry_run:
                    print("Dry run — skipping notifications.")

                # Save state
                save_state(new_state)

        finally:
            await browser.close()


def main():
    args = parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
