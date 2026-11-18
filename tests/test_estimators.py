import bootstrap  # noqa: F401  保证隔离模式下可导入项目包
import unittest
from datetime import date

from learning_path_outcomes.cohorts import Observation
from learning_path_outcomes.estimators import (aalen_johansen, bootstrap_cif,
                                               cif_at, kaplan_meier)
from learning_path_outcomes.models import CENSORED, CAUSE_INTERRUPT, CAUSE_TARGET, CAUSE_TRANSFER


def _obs(sid, t, label):
    return Observation(sid, t, label, "", True, "仅起点课程", ("P100",))


class EstimatorTests(unittest.TestCase):
    def setUp(self):
        # 10 人：2 目标、2 转课、1 中断、5 删失，时间点互不重叠
        self.observations = [
            _obs("a", 30, CAUSE_TARGET), _obs("b", 60, CAUSE_TARGET),
            _obs("c", 40, CAUSE_TRANSFER), _obs("d", 90, CAUSE_TRANSFER),
            _obs("e", 70, CAUSE_INTERRUPT),
            _obs("f", 100, CENSORED), _obs("g", 120, CENSORED),
            _obs("h", 150, CENSORED), _obs("i", 180, CENSORED),
            _obs("j", 180, CENSORED),
        ]

    def test_cif_is_monotone_and_partitions_with_survival(self):
        points = aalen_johansen(self.observations)
        previous = {cause: 0.0 for cause in (CAUSE_TARGET, CAUSE_TRANSFER, CAUSE_INTERRUPT)}
        for point in points:
            for cause, value in point.cif.items():
                self.assertGreaterEqual(value + 1e-12, previous[cause])
                previous[cause] = value
            total = sum(point.cif.values())
            self.assertLessEqual(total, 1.0 + 1e-9)
        final = cif_at(points, 180)
        self.assertAlmostEqual(final[CAUSE_TARGET], 0.2, places=6)

    def test_kaplan_meier_bounds_and_ci(self):
        points = kaplan_meier(self.observations)
        self.assertTrue(all(0.0 <= p.ci_low <= p.survival <= p.ci_high <= 1.0
                            for p in points))
        self.assertAlmostEqual(points[-1].survival, 0.5, places=6)

    def test_bootstrap_interval_covers_point_estimate(self):
        points = aalen_johansen(self.observations)
        estimate = cif_at(points, 180)
        intervals = bootstrap_cif(self.observations, 180, replicates=100)
        for cause, value in estimate.items():
            low, high = intervals[cause]
            self.assertLessEqual(low - 1e-9, value)
            self.assertLessEqual(value, high + 1e-9)

    def test_ties_are_handled_in_same_risk_set(self):
        tied = [_obs("a", 30, CAUSE_TARGET), _obs("b", 30, CAUSE_TARGET),
                _obs("c", 30, CENSORED), _obs("d", 60, CENSORED)]
        points = aalen_johansen(tied)
        self.assertAlmostEqual(cif_at(points, 180)[CAUSE_TARGET], 0.5, places=6)


if __name__ == "__main__":
    unittest.main()
