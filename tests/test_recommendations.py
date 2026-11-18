import bootstrap  # noqa: F401  保证隔离模式下可导入项目包
import tempfile
import unittest
from datetime import date
from pathlib import Path

from learning_path_outcomes.recommendations import (as_of_view,
                                                    has_confirmed_achievement,
                                                    recommend)
from learning_path_outcomes.records import (read_achievements, read_courses,
                                            read_enrollments)
from learning_path_outcomes.storage import (list_recommendations,
                                            replace_learning_records,
                                            save_recommendation)

DATA = Path(__file__).parent.parent / "data"
INTAKE_START = date(2025, 2, 10)
INTAKE_END = date(2025, 3, 31)
HORIZON = 180


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.courses = read_courses(DATA / "courses.csv")
        self.enrollments = read_enrollments(DATA / "enrollments.csv")
        self.achievements = read_achievements(DATA / "achievements.csv")
        self.kwargs = dict(intake_start=INTAKE_START, intake_end=INTAKE_END,
                           horizon_days=HORIZON)

    def test_recommend_uses_only_confirmed_achievement_and_passes_gate(self):
        rec = recommend("S06", date(2026, 9, 30), self.courses,
                        self.enrollments, self.achievements, **self.kwargs)
        self.assertEqual(rec.decision, "可推荐")
        self.assertEqual(rec.target_course_id, "C300")
        self.assertTrue(rec.eligible)
        self.assertEqual(rec.observation_window["horizon_days"], 180)
        self.assertIn("目标成果", rec.outcome_definition["competing_outcomes"])
        self.assertTrue(rec.association_only)
        self.assertTrue(rec.reasons[0].startswith("同一起点 P100"))

    def test_prerequisite_uses_only_confirmed_work_visible_as_of(self):
        # S08 的成果 2025-10-20 才确认：9 月 1 日推荐时不符合资格
        early = recommend("S08", date(2025, 9, 1), self.courses,
                          self.enrollments, self.achievements, **self.kwargs)
        self.assertEqual(early.decision, "不符合先修资格")
        later = recommend("S08", date(2025, 11, 1), self.courses,
                          self.enrollments, self.achievements, **self.kwargs)
        self.assertNotEqual(later.decision, "不符合先修资格")
        # 直接核对 as_of 截断
        _, visible = as_of_view(date(2025, 9, 1), self.enrollments, self.achievements)
        self.assertFalse(has_confirmed_achievement("S08", "WORK", visible))

    def test_small_origin_returns_insufficient_evidence_no_population_fill(self):
        rec = recommend("S15", date(2026, 9, 30), self.courses,
                        self.enrollments, self.achievements, **self.kwargs)
        self.assertEqual(rec.decision, "证据不足")
        self.assertTrue(any("队列规模" in r for r in rec.reasons))
        # 理由中不允许出现用 P100 人群均值补齐的内容
        self.assertFalse(any("P100" in r for r in rec.reasons))

    def test_parallel_path_blocked_for_ordering(self):
        rec = recommend("S11", date(2026, 9, 30), self.courses,
                        self.enrollments, self.achievements, **self.kwargs)
        self.assertEqual(rec.decision, "证据不足")
        self.assertTrue(any("先后" in r for r in rec.reasons))

    def test_health_exit_without_work_is_ineligible_not_failed(self):
        rec = recommend("S13", date(2026, 9, 30), self.courses,
                        self.enrollments, self.achievements, **self.kwargs)
        self.assertEqual(rec.decision, "不符合先修资格")

    def test_late_entrant_not_comparable_to_evidence_cohort(self):
        rec = recommend("S14", date(2026, 9, 30), self.courses,
                        self.enrollments, self.achievements, **self.kwargs)
        self.assertEqual(rec.decision, "证据不足")
        self.assertTrue(any("可比性" in r for r in rec.reasons))

    def test_snapshot_is_immutable_against_later_records(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "rec.db"
            replace_learning_records(db, self.courses, self.enrollments, self.achievements)
            early = recommend("S08", date(2025, 9, 1), self.courses,
                              self.enrollments, self.achievements, **self.kwargs)
            snapshot_id = save_recommendation(db, early)
            before = list_recommendations(db)
            # 之后再为同一学员做推荐，旧快照内容与指纹不变
            recommend("S08", date(2025, 11, 1), self.courses,
                      self.enrollments, self.achievements, **self.kwargs)
            after = list_recommendations(db)
            self.assertEqual(before, [row for row in after if row[0] == snapshot_id])
            self.assertEqual(len(after), 1)  # 第二次未保存；只追加策略不覆盖旧行
            self.assertEqual(after[0][4], "不符合先修资格")

    def test_candidate_courses_only_those_offered_by_as_of(self):
        # C300 于 2025-09-01 开课；此前没有进阶候选
        rec = recommend("S06", date(2025, 8, 1), self.courses,
                        self.enrollments, self.achievements, **self.kwargs)
        self.assertEqual(rec.decision, "无适配课程")
        self.assertEqual(rec.candidate_courses, ())


if __name__ == "__main__":
    unittest.main()
