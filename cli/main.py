import argparse
import asyncio
import logging

from cli.notifier import send_assignments, send_grades
from cli.services import (
    collect_baseline,
    run_analyze,
    run_analyze_all,
    run_authenticated,
    run_monitor_mode,
    run_snapshot,
)

log = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Moodle Scraper Bot")
    parser.add_argument("--headed", action="store_true", help="Show browser window")
    parser.add_argument("--verbose", action="store_true", help="Print scraped data")
    parser.add_argument("--dry-run", action="store_true", help="Scrape but don't notify")
    parser.add_argument(
        "--first-run",
        action="store_true",
        help="Save initial state without sending notifications",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Force re-login (opens browser for Google OAuth)",
    )
    parser.add_argument(
        "--assignments",
        action="store_true",
        help="Send current assignment list to Discord",
    )
    parser.add_argument(
        "--grades",
        action="store_true",
        help="Send current grades to Discord",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Download materials and generate AI learning recommendations",
    )
    parser.add_argument(
        "--analyze-all",
        action="store_true",
        help="Analyze all courses together in one unified study plan",
    )
    args = parser.parse_args()

    if args.analyze and args.analyze_all:
        parser.error(
            "Cannot use --analyze and --analyze-all together. "
            "Use --analyze for per-course analysis or --analyze-all for one unified plan."
        )

    if (args.assignments or args.grades) and (args.analyze or args.analyze_all):
        parser.error(
            "Cannot combine snapshot mode (--assignments/--grades) with analysis mode "
            "(--analyze/--analyze-all). Run them separately."
        )

    return args


def pick_courses(courses: list[tuple[str, str, str]]) -> list[str] | None:
    """Interactive course selection, returns selected course IDs or None for all."""
    print("\nAvailable courses:")
    for i, (cid, name, _) in enumerate(courses, 1):
        print(f"  {i}. {name} [{cid}]")
    print("  0. All courses")

    choice = input("\nEnter course numbers (comma-separated, e.g. 1,3,5): ").strip()
    if choice == "0":
        return None

    selected_ids = []
    for part in choice.split(","):
        try:
            idx = int(part.strip()) - 1
            if 0 <= idx < len(courses):
                selected_ids.append(courses[idx][0])
        except ValueError:
            continue

    if not selected_ids:
        print("No valid selection, using all courses.")
        return None

    selected_names = [name for cid, name, _ in courses if cid in selected_ids]
    print(f"\nSelected: {', '.join(selected_names)}")
    return selected_ids


async def run(args):
    async def _action(page):
        if args.assignments or args.grades:
            snapshot = await run_snapshot(
                page,
                include_assignments=args.assignments,
                include_grades=args.grades,
                verbose=args.verbose,
            )

            sent_any = False
            if args.assignments:
                sent_any = send_assignments(snapshot.assignments) or sent_any
            if args.grades:
                sent_any = send_grades(snapshot.grades) or sent_any

            if not sent_any:
                print("No assignment/grade content sent to Discord.")
            return

        if args.analyze or args.analyze_all:
            courses, _, _ = await collect_baseline(page, verbose=args.verbose)
            selectors = pick_courses(courses)

            if args.analyze_all:
                analysis_path = await run_analyze_all(page, selectors=selectors)
                if analysis_path:
                    print(f"\nSaved to: {analysis_path}")
                else:
                    print("\nNo materials extracted from selected courses. Nothing to analyze.")
            else:
                files = await run_analyze(page, selectors=selectors)
                if files:
                    print("\nSaved analyses:")
                    for path in files:
                        print(f"  - {path}")
                else:
                    print("\nNo analyses generated from selected courses.")
            return

        result = await run_monitor_mode(
            page,
            verbose=args.verbose,
            dry_run=args.dry_run,
            first_run=args.first_run,
            notify=not (args.first_run or args.dry_run),
        )
        print(f"\nChanges: {result.changes_summary}")
        if args.first_run:
            print("First run - skipping notifications, saving initial state.")
        elif args.dry_run:
            print("Dry run - skipping notifications.")

    await run_authenticated(_action, headed=args.headed, force_login=args.login)


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
