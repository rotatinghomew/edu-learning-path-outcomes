"""无第三方依赖的生存与竞争风险估计。

* :func:`kaplan_meier` 乘积极限生存曲线，附 Greenwood 对数变换置信区间；
* :func:`aalen_johansen` 在竞争风险下估计各结局的累积发生函数（CIF），
  自动处理同时间点的事件；
* :func:`bootstrap_cif` 对学员重采样，给出 CIF 的百分位置信区间，
  小样本下用于表达证据不确定性，而不是用总体平均掩盖差异。
"""
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from .models import CENSORED, COMPETING_CAUSES
from .cohorts import Observation


@dataclass(frozen=True)
class SurvivalPoint:
    time_days: int
    survival: float
    variance: float
    ci_low: float
    ci_high: float
    at_risk: int


@dataclass(frozen=True)
class CifPoint:
    time_days: int
    cif: Dict[str, float]
    at_risk: int


@dataclass(frozen=True)
class RiskSetRow:
    time_days: int
    at_risk: int
    events: Dict[str, int]
    censored: int


def _risk_sets(observations: Sequence[Observation]):
    """返回按时间排序的风险表 (time, n_risk, events_by_cause, censored)。"""
    times = sorted({obs.time_days for obs in observations})
    rows = []
    for t in times:
        at_risk = sum(1 for obs in observations if obs.time_days >= t)
        events = defaultdict(int)
        censored = 0
        for obs in observations:
            if obs.time_days == t:
                if obs.label == CENSORED:
                    censored += 1
                else:
                    events[obs.label] += 1
        rows.append(RiskSetRow(time_days=t, at_risk=at_risk,
                               events=dict(events), censored=censored))
    return rows


def kaplan_meier(observations: Sequence[Observation], confidence=0.95) -> List[SurvivalPoint]:
    z = 1.959963984540054 if abs(confidence - 0.95) < 1e-9 else _normal_quantile(
        1 - (1 - confidence) / 2)
    rows = _risk_sets(observations)
    survival = 1.0
    cumulative_variance = 0.0
    points = []
    for row in rows:
        d = sum(row.events.values())
        if d:
            survival *= (row.at_risk - d) / row.at_risk
            if row.at_risk > d:
                cumulative_variance += d / (row.at_risk * (row.at_risk - d))
        se = math.sqrt(cumulative_variance)
        if survival <= 0:
            low, high = 0.0, 0.0
        else:
            margin = z * se
            low = min(1.0, max(0.0, survival ** math.exp(margin)))
            high = min(1.0, max(0.0, survival ** math.exp(-margin)))
        points.append(SurvivalPoint(row.time_days, survival, cumulative_variance,
                                    low, high, row.at_risk))
    return points


def aalen_johansen(observations: Sequence[Observation],
                   causes=COMPETING_CAUSES) -> List[CifPoint]:
    """Aalen–Johansen 估计：CIF_k(t) = Σ S(t-)/n_t · dN_k(t)。"""
    rows = _risk_sets(observations)
    survival = 1.0
    cif = {cause: 0.0 for cause in causes}
    points = []
    for row in rows:
        d = sum(row.events.values())
        if d:
            for cause in causes:
                cif[cause] += survival * row.events.get(cause, 0) / row.at_risk
            survival *= (row.at_risk - d) / row.at_risk
        points.append(CifPoint(row.time_days, dict(cif), row.at_risk))
    return points


def cif_at(points: Sequence[CifPoint], horizon_days: int) -> Dict[str, float]:
    """取观察窗末（含）的 CIF；窗内无事件点时各结局为 0。"""
    latest = {cause: 0.0 for cause in COMPETING_CAUSES}
    for point in points:
        if point.time_days <= horizon_days:
            latest = dict(point.cif)
    return latest


def bootstrap_cif(observations: Sequence[Observation], horizon_days: int,
                  replicates=400, seed=20260930) -> Dict[str, Tuple[float, float]]:
    """对学员整体重采样的 CIF 百分位置信区间（固定随机种子，结果可复现）。"""
    rng = random.Random(seed)
    if not observations:
        return {cause: (0.0, 0.0) for cause in COMPETING_CAUSES}
    samples: Dict[str, List[float]] = defaultdict(list)
    n = len(observations)
    for _ in range(replicates):
        resampled = [rng.choice(observations) for _ in range(n)]
        estimates = cif_at(aalen_johansen(resampled), horizon_days)
        for cause, value in estimates.items():
            samples[cause].append(value)
    intervals = {}
    for cause, values in samples.items():
        values.sort()
        lower = values[max(0, int(0.025 * len(values)))]
        upper = values[min(len(values) - 1, int(0.975 * len(values)))]
        intervals[cause] = (lower, upper)
    return intervals


def _normal_quantile(p):
    # Beasley-Springer-Moro 逆正态近似，覆盖非 95% 置信度需求
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
           ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
