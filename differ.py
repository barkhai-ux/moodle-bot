import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from config import STATE_FILE
from models import Assignment, Grade, Material, to_dict

log = logging.getLogger(__name__)


@dataclass
class Changes:
    new_assignments: list[dict] = field(default_factory=list)
    new_grades: list[dict] = field(default_factory=list)
    grade_updates: list[tuple[dict, dict]] = field(default_factory=list)
    new_materials: list[dict] = field(default_factory=list)
    upcoming_deadlines: list[dict] = field(default_factory=list)

    def has_any(self) -> bool:
        return bool(
            self.new_assignments
            or self.new_grades
            or self.grade_updates
            or self.new_materials
            or self.upcoming_deadlines
        )

    def summary(self) -> str:
        parts = []
        if self.new_assignments:
            parts.append(f"{len(self.new_assignments)} new assignment(s)")
        if self.new_grades:
            parts.append(f"{len(self.new_grades)} new grade(s)")
        if self.grade_updates:
            parts.append(f"{len(self.grade_updates)} grade update(s)")
        if self.new_materials:
            parts.append(f"{len(self.new_materials)} new material(s)")
        if self.upcoming_deadlines:
            parts.append(f"{len(self.upcoming_deadlines)} upcoming deadline(s)")
        return ", ".join(parts) if parts else "no changes"


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"assignments": {}, "grades": {}, "materials": {}}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["last_run"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    log.info("State saved to %s", STATE_FILE)


def build_state(
    assignments: list[Assignment],
    grades: list[Grade],
    materials: list[Material],
) -> dict:
    return {
        "assignments": {a.key: to_dict(a) for a in assignments},
        "grades": {g.key: to_dict(g) for g in grades},
        "materials": {m.key: to_dict(m) for m in materials},
    }


def _is_due_soon(due_date_str: str | None, hours: int = 48) -> bool:
    """Check if a due date string is within the next N hours."""
    if not due_date_str:
        return False
    # Moodle date formats vary, try common ones
    for fmt in ("%d %B %Y, %I:%M %p", "%B %d, %Y, %I:%M %p",
                "%d %b %Y, %H:%M", "%Y-%m-%d %H:%M"):
        try:
            due = datetime.strptime(due_date_str.strip(), fmt)
            now = datetime.now()
            return now < due <= now + timedelta(hours=hours)
        except ValueError:
            continue
    return False


def compute_changes(old_state: dict, new_state: dict) -> Changes:
    changes = Changes()

    old_assign = old_state.get("assignments", {})
    new_assign = new_state.get("assignments", {})

    # New assignments
    for key, assign in new_assign.items():
        if key not in old_assign:
            changes.new_assignments.append(assign)

    # Upcoming deadlines
    for key, assign in new_assign.items():
        if _is_due_soon(assign.get("due_date")):
            changes.upcoming_deadlines.append(assign)

    # Grades
    old_grades = old_state.get("grades", {})
    new_grades = new_state.get("grades", {})

    for key, grade in new_grades.items():
        old_grade = old_grades.get(key)
        if old_grade is None:
            changes.new_grades.append(grade)
        elif old_grade.get("grade") != grade.get("grade"):
            changes.grade_updates.append((old_grade, grade))

    # New materials
    old_mats = old_state.get("materials", {})
    new_mats = new_state.get("materials", {})

    for key, mat in new_mats.items():
        if key not in old_mats:
            changes.new_materials.append(mat)

    return changes
