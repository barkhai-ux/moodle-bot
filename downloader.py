import logging
import re
from pathlib import Path

from config import DOWNLOADS_DIR

log = logging.getLogger(__name__)

# File extensions we want to download
SUPPORTED_EXTENSIONS = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".zip"}


def _sanitize_filename(name: str) -> str:
    """Remove invalid characters from filename."""
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip()


async def download_course_materials(page, materials: list[dict], course_name: str) -> list[Path]:
    """Download PDF/PPTX files from a course's material links.

    Returns list of paths to downloaded files.
    """
    course_dir = DOWNLOADS_DIR / _sanitize_filename(course_name)
    course_dir.mkdir(parents=True, exist_ok=True)

    downloaded = []

    for mat in materials:
        url = mat.get("url", "")
        title = mat.get("title", "unknown")
        rtype = mat.get("resource_type", "")

        # Only download file-type resources
        if rtype != "file":
            continue

        log.info("  Downloading: %s", title)

        try:
            # Moodle resource links trigger a direct download.
            # Use expect_download BEFORE clicking/navigating.
            async with page.expect_download(timeout=30000) as download_info:
                # Use JavaScript navigation to avoid goto's download conflict
                await page.evaluate(f"window.location.href = '{url}'")

            download = await download_info.value
            suggested = download.suggested_filename
            ext = Path(suggested).suffix.lower()

            if ext not in SUPPORTED_EXTENSIONS:
                log.info("    Skipping %s (unsupported type: %s)", suggested, ext)
                await download.delete()
                continue

            save_path = course_dir / _sanitize_filename(suggested)

            # Skip if already downloaded
            if save_path.exists():
                log.info("    Already exists: %s", save_path.name)
                await download.delete()
                downloaded.append(save_path)
                continue

            await download.save_as(str(save_path))
            downloaded.append(save_path)
            log.info("    Saved: %s", save_path.name)

        except Exception as e:
            log.warning("    Failed to download %s: %s", title, e)
            continue

    log.info("  Downloaded %d files for %s.", len(downloaded), course_name)
    return downloaded
