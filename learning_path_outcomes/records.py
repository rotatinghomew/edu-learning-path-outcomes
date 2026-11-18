import csv
from datetime import date
from pathlib import Path

from .models import Achievement, Course, Enrollment


def _parse_day(value):
    value = (value or "").strip()
    return date.fromisoformat(value) if value else None


def read_records(path):
    """读取旧式聚合观察记录（保留兼容）。"""
    with Path(path).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        return []
    required = {"period", "group", "count", "value"}
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"缺少字段: {', '.join(sorted(missing))}")
    return rows


def read_courses(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    courses = []
    for row in rows:
        courses.append(Course(
            course_id=row["course_id"].strip(),
            name=row["name"].strip(),
            level=row["level"].strip(),
            offer_start=date.fromisoformat(row["offer_start"].strip()),
            offer_end=_parse_day(row.get("offer_end", "")),
            prereq_achievement=(row.get("prereq_achievement") or "").strip() or None,
        ))
    return courses


def read_enrollments(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    enrollments = []
    for row in rows:
        enrollments.append(Enrollment(
            student_id=row["student_id"].strip(),
            course_id=row["course_id"].strip(),
            entry_date=date.fromisoformat(row["entry_date"].strip()),
            exit_date=_parse_day(row.get("exit_date", "")),
            exit_status=row["exit_status"].strip(),
            exit_reason=(row.get("exit_reason") or "").strip(),
        ))
    return enrollments


def read_achievements(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return [Achievement(
        student_id=row["student_id"].strip(),
        achievement_code=row["achievement_code"].strip(),
        confirm_date=date.fromisoformat(row["confirm_date"].strip()),
    ) for row in rows]
