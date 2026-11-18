"""路径分析：时间顺序、并行修读、等待时间与证据适用性。

关键纪律：
* 并行注册的课程不虚构先后；无法区分时间顺序的路径直接标记证据不足，
  不会被并入顺序路径统计。
* 后续课程的事件时间从该课程实际进入日起算；进入前的等待不进入
  后续课程的成功经验，只作为队列特征单独报告。
* 路径好看只构成关联：进入后续课程的学员本就是坚持下来的子人群，
  证据说明必须带选择限制，禁止解释为课程本身造成了收益。
"""
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from .cohorts import Observation, build_cohort
from .estimators import (aalen_johansen, bootstrap_cif, cif_at, _risk_sets)
from .models import (CENSORED, COMPETING_CAUSES, Enrollment, STATUS_INTERRUPT,
                     STATUS_TRANSFER)

# 证据充足的默认门槛：队列规模、拥有完整随访的人数
MIN_COHORT = 8
MIN_MATURED = 3


@dataclass(frozen=True)
class WaitingTime:
    student_id: str
    prior_course_id: str
    next_course_id: str
    prior_exit_day: object
    next_entry_day: object
    wait_days: int


@dataclass(frozen=True)
class CourseExperience:
    """后续课程层面的时间-事件：自实际进入日起算，等待时间不计入。"""
    student_id: str
    course_id: str
    entry_day: object
    time_days: int
    label: str
    reason: str


@dataclass(frozen=True)
class PathGroup:
    name: str
    members: Tuple[str, ...]
    path_courses: Tuple[Tuple[str, ...], ...]
    ordering_distinguishable: bool
    note: str


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: Tuple[str, ...]


@dataclass(frozen=True)
class PathEvidence:
    origin_course: str
    cohort_size: int
    matured: int
    horizon_days: int
    overall_cif: Dict[str, float]
    overall_ci: Dict[str, Tuple[float, float]]
    risk_sets: Tuple
    path_groups: Tuple[PathGroup, ...]
    group_cif: Dict[str, Dict[str, float]]
    waiting_times: Tuple[WaitingTime, ...]
    waiting_days_summary: Dict[str, float]
    course_experience: Tuple[CourseExperience, ...]
    gate: GateResult
    association_only: bool
    caveats: Tuple[str, ...]


def entry_timelines(enrollments: Sequence[Enrollment]) -> Dict[str, List[Enrollment]]:
    """按学员返回按进入日排序的注册时间线。"""
    timelines: Dict[str, List[Enrollment]] = {}
    for enr in enrollments:
        timelines.setdefault(enr.student_id, []).append(enr)
    for records in timelines.values():
        records.sort(key=lambda enr: (enr.entry_date, enr.course_id))
    return timelines


def detect_parallel(timeline: Sequence[Enrollment]) -> bool:
    """存在注册区间重叠即判定为并行修读。"""
    for i, left in enumerate(timeline):
        for right in timeline[i + 1:]:
            left_end = left.exit_date or right.entry_date
            right_end = right.exit_date or left.entry_date
            if left.entry_date < right_end and right.entry_date < left_end:
                return True
    return False


def waiting_before_next(timeline: Sequence[Enrollment]) -> List[WaitingTime]:
    """前一门课退出日到下一门课进入日之间的等待；并行（无空档）不产生等待。"""
    result = []
    for prior, nxt in zip(timeline, timeline[1:]):
        if prior.exit_date is None or nxt.entry_date <= prior.exit_date:
            continue
        result.append(WaitingTime(
            student_id=prior.student_id, prior_course_id=prior.course_id,
            next_course_id=nxt.course_id, prior_exit_day=prior.exit_date,
            next_entry_day=nxt.entry_date,
            wait_days=(nxt.entry_date - prior.exit_date).days,
        ))
    return result


def course_level_experience(enrollments: Sequence[Enrollment], achievements,
                            course_id: str) -> List[CourseExperience]:
    """从课程实际进入日起算事件；等待时间被结构性排除在分母之外。"""
    result = []
    for enr in enrollments:
        if enr.course_id != course_id:
            continue
        if enr.exit_date is None:
            label, reason, event_day = CENSORED, "仍在学", None
        elif enr.exit_status == STATUS_TRANSFER:
            label, reason, event_day = "转入其他路径", enr.exit_reason or "转课", enr.exit_date
        elif enr.exit_status == STATUS_INTERRUPT:
            label, reason, event_day = "中断", enr.exit_reason or "中断", enr.exit_date
        else:
            label, reason, event_day = CENSORED, "课程完成（无窗内目标事件）", enr.exit_date
        target = [a.confirm_date for a in achievements
                  if a.student_id == enr.student_id and a.confirm_date >= enr.entry_date]
        if target and (event_day is None or min(target) <= event_day):
            label, reason, event_day = "目标成果", "作品确认", min(target)
        if event_day is None:
            time_days = None
        else:
            time_days = (event_day - enr.entry_date).days
        result.append(CourseExperience(
            student_id=enr.student_id, course_id=course_id, entry_day=enr.entry_date,
            time_days=time_days if time_days is not None else 0,
            label=label, reason=reason,
        ))
    return result


def _group_observations(observations: Sequence[Observation]) -> Tuple[PathGroup, ...]:
    grouped: Dict[str, List[Observation]] = {}
    for obs in observations:
        grouped.setdefault(obs.subgroup, []).append(obs)
    result = []
    for name in sorted(grouped):
        members_obs = sorted(grouped[name], key=lambda o: o.student_id)
        distinguishable = name != "并行修读（先后不可区分）"
        note = ("注册区间重叠，无法区分课程先后，不生成顺序路径证据"
                if not distinguishable
                else "按实际进入日可确认先后顺序")
        result.append(PathGroup(
            name=name,
            members=tuple(o.student_id for o in members_obs),
            path_courses=tuple(sorted({o.path_courses for o in members_obs})),
            ordering_distinguishable=distinguishable, note=note,
        ))
    return tuple(result)


def evaluate_origin(origin_course, intake_start, intake_end, cutoff, horizon_days,
                    enrollments, achievements, min_cohort=MIN_COHORT,
                    min_matured=MIN_MATURED, replicates=400):
    """汇总一个起点人群的全部路径证据与适用性门槛。"""
    observations, coverage = build_cohort(
        origin_course, intake_start, intake_end, cutoff, horizon_days,
        enrollments, achievements)
    cif_points = aalen_johansen(observations)
    overall_cif = cif_at(cif_points, horizon_days)
    overall_ci = bootstrap_cif(observations, horizon_days, replicates=replicates)
    groups = _group_observations(observations)
    group_cif = {}
    for group in groups:
        sub = [o for o in observations if o.student_id in group.members]
        group_cif[group.name] = cif_at(aalen_johansen(sub), horizon_days)

    timelines = entry_timelines(enrollments)
    waits = [w for sid, timeline in timelines.items()
             if sid in coverage.eligible for w in waiting_before_next(timeline)]
    wait_days = [w.wait_days for w in waits]
    wait_summary = {
        "n": len(wait_days),
        "mean_days": sum(wait_days) / len(wait_days) if wait_days else 0.0,
        "max_days": max(wait_days) if wait_days else 0,
    }
    followup_courses = {cid for enr in enrollments if enr.course_id != origin_course
                        for cid in [enr.course_id]}
    experiences = tuple(exp for cid in sorted(followup_courses)
                        for exp in course_level_experience(enrollments, achievements, cid)
                        if exp.student_id in coverage.eligible)

    matured = sum(1 for o in observations if o.matured)
    reasons = []
    if len(observations) < min_cohort:
        reasons.append(f"队列规模 {len(observations)} 人，低于最小要求 {min_cohort} 人")
    if matured < min_matured:
        reasons.append(f"完整随访 {matured} 人，低于最小要求 {min_matured} 人")
    gate = GateResult(passed=not reasons, reasons=tuple(reasons))
    caveats = (
        "路径与结局仅为关联：进入后续课程的学员已通过坚持性自我选择，不能归因于课程本身",
        "等待时间不计入后续课程的时间-事件分母，课程经验自实际进入日起算",
        "受保护退出（健康/时间安排）与观察结束仍在学按删失处理，不计为未完成",
    )
    return PathEvidence(
        origin_course=origin_course, cohort_size=len(observations), matured=matured,
        horizon_days=horizon_days, overall_cif=overall_cif, overall_ci=overall_ci,
        risk_sets=tuple(_risk_sets(observations)), path_groups=groups,
        group_cif=group_cif, waiting_times=tuple(waits),
        waiting_days_summary=wait_summary, course_experience=experiences,
        gate=gate, association_only=True, caveats=caveats,
    ), coverage
