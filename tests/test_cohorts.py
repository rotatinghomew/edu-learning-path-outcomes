import bootstrap  # noqa: F401  保证隔离模式下可导入项目包
import unittest
from datetime import date

from learning_path_outcomes.cohorts import build_cohort
from learning_path_outcomes.models import (
    CENSORED, CAUSE_INTERRUPT, CAUSE_TARGET, CAUSE_TRANSFER,
    Achievement, Enrollment)

INTAKE_START = date(2025, 2, 10)
INTAKE_END = date(2025, 3, 31)
CUTOFF = date(2026, 9, 30)
HORIZON = 180


def _load():
    from learning_path_outcomes.records import (read_achievements, read_courses,
                                                 read_enrollments)
    from pathlib import Path
    data = Path(__file__).parent.parent / "data"
    return (read_courses(data / "courses.csv"),
            read_enrollments(data / "enrollments.csv"),
            read_achievements(data / "achievements.csv"))


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.courses, self.enrollments, self.achievements = _load()

    def test_photography_cohort_risks_and_competing_outcomes(self):
        observations, coverage = build_cohort(
            "P100", INTAKE_START, INTAKE_END, CUTOFF, HORIZON,
            self.enrollments, self.achievements)
        labels = {o.student_id: o.label for o in observations}
        self.assertEqual(len(observations), 13)
        self.assertEqual(coverage.event_counts[CAUSE_TARGET], 4)
        self.assertEqual(coverage.event_counts[CAUSE_TRANSFER], 1)
        self.assertEqual(coverage.event_counts[CAUSE_INTERRUPT], 2)
        self.assertEqual(coverage.event_counts[CENSORED], 6)
        # 在学与健康退出不是失败
        self.assertEqual(labels["S10"], CENSORED)   # 观察结束仍在学
        self.assertEqual(labels["S13"], CENSORED)   # 健康原因受保护删失
        self.assertIn("S13", coverage.protected_censored)
        self.assertIn("S10", coverage.ongoing_at_cutoff)
        # 目标成果以确认日为准：S08 的作品在 180 天窗外，窗内按删失
        s08 = next(o for o in observations if o.student_id == "S08")
        self.assertEqual(s08.label, CENSORED)

    def test_late_and_insufficient_followup_are_excluded_not_failed(self):
        _, coverage = build_cohort(
            "P100", INTAKE_START, INTAKE_END, CUTOFF, HORIZON,
            self.enrollments, self.achievements)
        # S14 起点进入晚于招生窗口（同时观察窗也不满），归入窗口外晚到而非失败
        self.assertEqual(coverage.excluded_late, ("S14",))
        self.assertEqual(coverage.excluded_insufficient, ())

    def test_first_event_only_transfer_beats_later_work(self):
        enrollments = [
            Enrollment("T1", "P100", date(2025, 2, 10), date(2025, 5, 1),
                       "转课", "改方向"),
        ]
        achievements = [Achievement("T1", "WORK", date(2025, 6, 1))]
        observations, _ = build_cohort(
            "P100", INTAKE_START, INTAKE_END, CUTOFF, HORIZON,
            enrollments, achievements)
        self.assertEqual(observations[0].label, CAUSE_TRANSFER)

    def test_schedule_reason_is_protected_censoring(self):
        enrollments = [
            Enrollment("T2", "P100", date(2025, 2, 10), date(2025, 4, 1),
                       "中断", "时间安排"),
        ]
        observations, coverage = build_cohort(
            "P100", INTAKE_START, INTAKE_END, CUTOFF, HORIZON,
            enrollments, [])
        self.assertEqual(observations[0].label, CENSORED)
        self.assertIn("T2", coverage.protected_censored)


if __name__ == "__main__":
    unittest.main()
