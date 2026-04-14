from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Assignment:
    course_name: str
    title: str
    due_date: Optional[str]
    status: str
    url: str
    course_id: str

    @property
    def key(self):
        return f"{self.course_id}:{self.title}"


@dataclass
class Grade:
    course_name: str
    grade: str
    feedback: Optional[str]
    url: str
    course_id: str

    @property
    def key(self):
        return f"{self.course_id}:{self.course_name}"


@dataclass
class Material:
    course_name: str
    title: str
    resource_type: str
    url: str
    section_name: str
    course_id: str

    @property
    def key(self):
        return f"{self.course_id}:{self.title}:{self.url}"


def to_dict(obj):
    return asdict(obj)
