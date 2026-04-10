import logging
from urllib.parse import urlparse, parse_qs

from config import BASE_URL, DASHBOARD_URL, GRADES_OVERVIEW_URL, SEL_COURSE_LINK
from models import Assignment, Grade, Material

log = logging.getLogger(__name__)


def _extract_course_id(href: str) -> str:
    """Extract course ID from a Moodle URL like /course/view.php?id=123."""
    parsed = urlparse(href)
    params = parse_qs(parsed.query)
    return params.get("id", [""])[0]


async def scrape_courses(page) -> list[tuple[str, str, str]]:
    """Return list of (course_id, course_name, course_url) from the My Courses page."""
    courses_url = f"{BASE_URL}/my/courses.php"
    await page.goto(courses_url, timeout=30000)
    await page.wait_for_load_state("networkidle")

    # Wait for course cards to render (they're loaded dynamically)
    try:
        await page.wait_for_selector(SEL_COURSE_LINK, timeout=10000)
    except Exception:
        log.warning("No course links appeared after waiting.")

    links = await page.query_selector_all(SEL_COURSE_LINK)
    courses = []
    seen_ids = set()

    for link in links:
        href = await link.get_attribute("href") or ""
        name = (await link.inner_text()).strip()
        cid = _extract_course_id(href)

        if not cid or not name or cid in seen_ids:
            continue
        seen_ids.add(cid)
        courses.append((cid, name, href))

    log.info("Found %d courses.", len(courses))
    return courses


async def scrape_assignments(page) -> list[Assignment]:
    """Scrape assignments from the dashboard timeline (/my/).

    Moodle's dashboard has a timeline with upcoming activities.
    Structure:
      [data-region="event-list-wrapper"]
        > [data-region="event-list-content-date"]  (date heading)
        > div[data-region="event-list-item"]        (event item)
          > .event-name a                           (title + link)
          > .event-name-container > small           (type · course name)
          > .timeline-name > small                  (time)
    """
    assignments = []

    log.info("Scraping assignments from dashboard timeline...")
    await page.goto(DASHBOARD_URL, timeout=30000)
    await page.wait_for_load_state("networkidle")

    # Wait for the timeline to render
    try:
        await page.wait_for_selector('[data-region="event-list-item"]', timeout=10000)
    except Exception:
        log.warning("Timeline items did not appear after waiting.")

    # Click "Show more activities" until no more button exists
    for _ in range(10):  # safety limit
        btn = await page.query_selector(
            '[data-region="more-events-button-container"] button[data-action="more-events"]'
        )
        if not btn or not await btn.is_visible():
            break
        await btn.click()
        await page.wait_for_timeout(1000)

    # Parse timeline items
    wrapper = await page.query_selector('[data-region="event-list-wrapper"]')
    if not wrapper:
        log.warning("No timeline wrapper found on dashboard.")
        return assignments

    children = await wrapper.query_selector_all(":scope > div")
    current_date = ""

    for child in children:
        # Check if this is a date heading
        data_region = await child.get_attribute("data-region")
        if data_region == "event-list-content-date":
            current_date = (await child.inner_text()).strip()
            continue

        # Event items: the direct child div may not have data-region="event-list-item"
        # but contains a nested div with it, or simply contains the event content.
        # Look for the event link inside this child.
        event = await child.query_selector('[data-region="event-list-item"]')
        target = event if event else child

        link = await target.query_selector(".event-name a, h6 a")
        if not link:
            continue

        title = (await link.inner_text()).strip()
        href = await link.get_attribute("href") or ""

        # Extract time
        time_el = await target.query_selector("small")
        time_text = ""
        if time_el:
            time_text = (await time_el.inner_text()).strip()

        # Extract description: "Assignment is due · Course Name"
        desc_el = await target.query_selector(".event-name-container > small")
        course_name = ""
        act_type = ""
        if desc_el:
            desc = (await desc_el.inner_text()).strip()
            if "\u00b7" in desc:  # middle dot ·
                parts = desc.split("\u00b7", 1)
                act_type = parts[0].strip()
                course_name = parts[1].strip()

        # Build due date from date heading + time
        due_date = f"{current_date}, {time_text}" if current_date and time_text else current_date

        cid = _extract_course_id(href) if "id=" in href else ""

        assignments.append(Assignment(
            course_name=course_name,
            title=title,
            due_date=due_date or None,
            status=act_type,
            url=href,
            course_id=cid,
        ))

    log.info("Found %d assignments from dashboard.", len(assignments))
    return assignments


async def scrape_grades(page, courses: list[tuple[str, str, str]]) -> list[Grade]:
    """Scrape grades from the grades overview page."""
    grades = []

    log.info("Scraping grades overview...")
    try:
        await page.goto(GRADES_OVERVIEW_URL, timeout=30000)
        await page.wait_for_load_state("domcontentloaded")
    except Exception as e:
        log.warning("Failed to load grades overview: %s", e)
        return grades

    rows = await page.query_selector_all("table.generaltable tbody tr")

    for row in rows:
        cells = await row.query_selector_all("td")
        if len(cells) < 2:
            continue

        name_el = await cells[0].query_selector("a")
        if name_el:
            cname = (await name_el.inner_text()).strip()
            grade_url = await name_el.get_attribute("href") or ""
        else:
            cname = (await cells[0].inner_text()).strip()
            grade_url = ""

        grade_text = (await cells[1].inner_text()).strip() or "-"
        cid = _extract_course_id(grade_url)

        grades.append(Grade(
            course_name=cname,
            grade=grade_text,
            feedback=None,
            url=grade_url,
            course_id=cid,
        ))

    log.info("Found %d grade entries.", len(grades))
    return grades


# Resource type patterns in Moodle URLs
_RESOURCE_PATTERNS = {
    "/mod/resource/": "file",
    "/mod/url/": "url",
    "/mod/page/": "page",
    "/mod/folder/": "folder",
    "/mod/book/": "book",
}


def _classify_resource(href: str) -> str | None:
    """Return resource type if href is a known material type, else None."""
    for pattern, rtype in _RESOURCE_PATTERNS.items():
        if pattern in href:
            return rtype
    return None


async def _get_activity_title(link) -> str:
    """Extract clean activity title, excluding the hidden accesshide span."""
    # The link contains: <span class="instancename">Title <span class="accesshide">Type</span></span>
    instancename = await link.query_selector(".instancename")
    if instancename:
        # Get text content, then remove the accesshide part
        full_text = (await instancename.inner_text()).strip()
        accesshide = await instancename.query_selector(".accesshide")
        if accesshide:
            hidden_text = (await accesshide.inner_text()).strip()
            return full_text.replace(hidden_text, "").strip()
        return full_text
    return (await link.inner_text()).strip()


async def scrape_materials(page, courses: list[tuple[str, str, str]]) -> list[Material]:
    """Scrape course materials by visiting each course's page.

    Course page structure:
      li.section.course-section[data-sectionname="Week 1"]
        > li[data-for="cmitem"].modtype_resource
          > a[href*="/mod/"]
            > span.instancename
              > "Title"
              > span.accesshide "File"
    """
    materials = []

    for cid, cname, curl in courses:
        log.info("Scraping materials for %s...", cname)

        try:
            await page.goto(curl, timeout=30000)
            await page.wait_for_load_state("networkidle")
            # Wait for course sections to render
            await page.wait_for_selector("li.section.course-section", timeout=10000)
        except Exception as e:
            log.warning("Failed to load course page for %s: %s", cname, e)
            continue

        sections = await page.query_selector_all("li.section.course-section")

        for section in sections:
            # Clean section name from data attribute
            section_name = await section.get_attribute("data-sectionname") or ""

            # Activity items
            cm_items = await section.query_selector_all("[data-for='cmitem']")

            seen_urls = set()
            for item in cm_items:
                link = await item.query_selector("a[href*='/mod/']")
                if not link:
                    continue

                href = await link.get_attribute("href") or ""
                if not href or href in seen_urls:
                    continue

                rtype = _classify_resource(href)
                if rtype is None:
                    continue

                seen_urls.add(href)
                title = await _get_activity_title(link)
                if not title:
                    continue

                materials.append(Material(
                    course_name=cname,
                    title=title,
                    resource_type=rtype,
                    url=href,
                    section_name=section_name,
                    course_id=cid,
                ))

    log.info("Found %d materials total.", len(materials))
    return materials
