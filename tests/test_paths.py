import bootstrap  # noqa: F401  保证隔离模式下可导入项目包
import unittest
from datetime import date
from pathlib import Path

from learning_path_outcomes.paths import (course_level_experience,
                                          detect_parallel, entry_timelines,
                                          evaluate_origin, waiting_before_next)
from learning_path_outcomes.records import (read_achievements, read_courses,
                                            read_enrollments)

DATA = Path(__file__).parent.parent / "data"
INTAKE_START = date(2025, 2, 10)
INTAKE_END = date(2025, 3, 31)
CUTOFF = date(2026, 9, 30)
HORIZON = 180


class PathTests(unittest.TestCase):
    def setUp(self):
        self.courses = read_courses(DATA / "courses.csv")
        self.enrollments = read_enrollments(DATA / "enrollments.csv")
        self.achievements = read_achievements(DATA / "achievements.csv")
        self.timelines = entry_timelines(self.enrollments)

    def test_parallel_enrollment_is_flagged_and_blocks_sequence_evidence(self):
        evidence, _ = evaluate_origin(
            "P100", INTAKE_START, INTAKE_END, CUTOFF, HORIZON,
            self.enrollments, self.achievements)
        parallel = next(g for g in evidence.path_groups if "并行" in g.name)
        self.assertFalse(parallel.ordering_distinguishable)
        self.assertEqual(set(parallel.members), {"S11", "S12"})
        # 并行组单独成组，未被并入顺序组
        sequential = next(g for g in evidence.path_groups if g.name == "顺序进入后续课程")
        self.assertNotIn("S11", sequential.members)

    def test_waiting_time_is_measured_but_not_credited_to_next_course(self):
        waits = {(w.student_id, w.next_course_id): w.wait_days
                 for w in waiting_before_next(self.timelines["S05"])}
        self.assertEqual(waits[("S05", "P200")], 81)   # 6/12 → 9/1
        evidence, _ = evaluate_origin(
            "P100", INTAKE_START, INTAKE_END, CUTOFF, HORIZON,
            self.enrollments, self.achievements)
        self.assertGreaterEqual(evidence.waiting_days_summary["n"], 1)
        # 课程经验自 P200 实际进入日起算：S05 仍在学，应为删失而非把等待算作在课时间
        p200 = {e.student_id: e for e in
                course_level_experience(self.enrollments, self.achievements, "P200")}
        self.assertEqual(p200["S05"].label, "删失")
        self.assertEqual(p200["S05"].time_days, 0)

    def test_evidence_gate_fails_for_small_calligraphy_origin(self):
        evidence, coverage = evaluate_origin(
            "X100", INTAKE_START, INTAKE_END, CUTOFF, HORIZON,
            self.enrollments, self.achievements)
        self.assertEqual(evidence.cohort_size, 3)
        self.assertFalse(evidence.gate.passed)
        self.assertTrue(any("队列规模" in r for r in evidence.gate.reasons))
        self.assertTrue(evidence.association_only)

    def test_photography_evidence_passes_gate_with_caveats(self):
        evidence, _ = evaluate_origin(
            "P100", INTAKE_START, INTAKE_END, CUTOFF, HORIZON,
            self.enrollments, self.achievements)
        self.assertTrue(evidence.gate.passed)
        self.assertEqual(evidence.cohort_size, 13)
        self.assertTrue(all("关联" in c or "删失" in c or "等待" in c
                            for c in evidence.caveats))


if __name__ == "__main__":
    unittest.main()
