import logging
from groq import Groq

from config import GROQ_API_KEY

log = logging.getLogger(__name__)

client = None


def _get_client() -> Groq:
    global client
    if client is None:
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY not set in .env")
        client = Groq(api_key=GROQ_API_KEY)
    return client


MAX_CHARS_PER_FILE = 8000
MAX_TOTAL_CHARS = 28000
MAX_TOTAL_CHARS_ALL = 40000
MAX_CHARS_PER_COURSE = 6000


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to fit within limits."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[... truncated ...]"


def _prioritize_materials(material_texts: dict[str, str]) -> str:
    """Combine materials smartly: prioritize slides over textbooks, recent over old."""
    slides = {}
    other = {}

    for filename, text in material_texts.items():
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext in ("pptx", "ppt"):
            slides[filename] = text
        else:
            other[filename] = text

    combined = ""
    budget = MAX_TOTAL_CHARS

    # Slides first (most relevant lecture content)
    for filename, text in slides.items():
        chunk = _truncate(text, MAX_CHARS_PER_FILE)
        if len(combined) + len(chunk) + 50 > budget:
            break
        combined += f"\n\n=== {filename} ===\n{chunk}"

    # Then PDFs (syllabus, guidelines — usually shorter and important)
    for filename, text in other.items():
        chunk = _truncate(text, MAX_CHARS_PER_FILE)
        if len(combined) + len(chunk) + 50 > budget:
            break
        combined += f"\n\n=== {filename} ===\n{chunk}"

    return combined


def analyze_course(
    course_name: str,
    material_texts: dict[str, str],
    grades: list[dict],
    assignments: list[dict],
) -> str:
    """Analyze course materials and return learning recommendations."""
    if not material_texts:
        return "No extracted materials were available to analyze for this course."

    c = _get_client()

    # Build context about the course
    grade_info = ""
    for g in grades:
        if g.get("course_name") == course_name:
            grade_info = f"Current grade: {g.get('grade', 'N/A')}"
            break

    assignment_info = ""
    relevant_assignments = [a for a in assignments if a.get("course_name") == course_name]
    if relevant_assignments:
        assignment_info = "Upcoming assignments:\n"
        for a in relevant_assignments:
            assignment_info += f"  - {a['title']} (Due: {a.get('due_date', 'N/A')})\n"

    # Combine materials smartly (slides first, truncated per file)
    combined_materials = _prioritize_materials(material_texts)
    log.info("  Combined material text: %d chars from %d files", len(combined_materials), len(material_texts))

    prompt = f"""You are a study advisor analyzing course materials for a student.

Course: {course_name}
{grade_info}
{assignment_info}

Below are the extracted texts from the course's lecture slides and documents:

{combined_materials}

Based on this content, provide a comprehensive learning guide with these sections:

## 📚 Key Concepts Summary
Summarize the main topics and concepts covered in these materials. Organize by lecture/chapter.

## 🎯 Study Priorities
Based on the material progression and any upcoming assignments, what should the student focus on right now? Rank by importance.

## ⚠️ Weak Areas to Watch
{"Based on the current grade (" + grade_info + "), identify" if grade_info else "Identify"} which topics might need extra attention. Flag concepts that build on each other where gaps could compound.

## 📝 Practice Questions
Generate 5-8 practice questions that test understanding of the key concepts. Include a mix of:
- Conceptual questions (explain/define)
- Application questions (apply concept to scenario)
- Analysis questions (compare/contrast/evaluate)

## 💡 Study Tips
Specific actionable advice for mastering this material.

Keep the response focused and actionable. Use clear formatting."""

    log.info("Sending analysis request to Groq for %s...", course_name)

    response = c.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=4000,
    )

    result = response.choices[0].message.content
    if not result:
        return "Analysis completed, but the AI service returned an empty response."
    log.info("Received analysis for %s (%d chars).", course_name, len(result))
    return result


def _build_course_summary(course_name: str, material_texts: dict[str, str]) -> str:
    """Build a truncated material summary for one course within a multi-course analysis."""
    combined = _prioritize_materials(material_texts)
    return _truncate(combined, MAX_CHARS_PER_COURSE)


def analyze_all_courses(
    all_materials: dict[str, dict[str, str]],
    grades: list[dict],
    assignments: list[dict],
) -> str:
    """Analyze all courses together and return a unified study guide.

    all_materials: {course_name: {filename: text}}
    """
    if not all_materials:
        return "No extracted materials were available to analyze across courses."

    c = _get_client()

    # Build grades summary
    grades_section = ""
    if grades:
        lines = []
        for g in grades:
            lines.append(f"  - {g.get('course_name', '?')}: {g.get('grade', 'N/A')}")
        grades_section = "Current grades:\n" + "\n".join(lines)

    # Build assignments summary
    assignments_section = ""
    if assignments:
        lines = []
        for a in assignments:
            lines.append(f"  - [{a.get('course_name', '?')}] {a['title']} (Due: {a.get('due_date', 'N/A')})")
        assignments_section = "Upcoming assignments:\n" + "\n".join(lines)

    # Build combined materials, budget split across courses
    combined_materials = ""
    budget = MAX_TOTAL_CHARS_ALL
    for course_name, texts in all_materials.items():
        if not texts:
            continue
        course_block = _build_course_summary(course_name, texts)
        header = f"\n\n{'='*40}\nCOURSE: {course_name}\n{'='*40}\n"
        block = header + course_block
        if len(combined_materials) + len(block) + 50 > budget:
            combined_materials += f"\n\n[... remaining courses truncated ...]"
            break
        combined_materials += block

    log.info("Combined all-courses material text: %d chars from %d courses",
             len(combined_materials), len(all_materials))

    prompt = f"""You are a study advisor analyzing ALL of a student's courses together to create one unified study plan.

{grades_section}
{assignments_section}

Below are extracted materials from each course:

{combined_materials}

Create a comprehensive cross-course study guide with these sections:

## Overall Semester Overview
Brief summary of what each course covers and how far along the student is.

## This Week's Priority Actions
A single ranked to-do list across ALL courses. Consider upcoming deadlines, assignment weights, and current grades to prioritize what matters most right now.

## Cross-Course Connections
Identify concepts, skills, or themes that overlap between courses. Where can studying one topic reinforce another?

## Per-Course Status

For each course, provide a short block:
### [Course Name]
- **Current standing:** grade + trajectory
- **Key focus areas:** what to study next
- **Risk flags:** anything falling behind or upcoming crunch

## Weekly Study Schedule Suggestion
Suggest how to distribute study time across courses for the coming week, based on deadlines and difficulty.

## Critical Deadlines & Warnings
List any deadlines within the next 2 weeks and flag courses where the student may be at risk.

Keep the response focused, actionable, and well-formatted."""

    log.info("Sending combined analysis request to Groq (%d courses)...", len(all_materials))

    response = c.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=6000,
    )

    result = response.choices[0].message.content
    if not result:
        return "Analysis completed, but the AI service returned an empty response."
    log.info("Received combined analysis (%d chars).", len(result))
    return result
