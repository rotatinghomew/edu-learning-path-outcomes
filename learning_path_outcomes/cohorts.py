"""风险集合、观察窗口与竞争结局界定。

口径要点（对应教务需求）：
* 队列只纳入在招生窗口内、从明确起点课程出发的学员；进入较晚、观察期不足者
  不进入分母，覆盖率中单独报告。
* 以起点进入日为各人的第 0 天，在相同观察期限 ``horizon_days`` 内比较结局，
  保证不同入门人群在各自相同的期限上可比。
* 只取第一项事件。观察结束仍在学、因健康/时间安排退出、以及超出观察窗才发生
  的事件都按删失处理，不记入失败。
* 目标成果以成果确认（而非课程注册状态）为准。
"""
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from .models import (
    CENSORED,
    CAUSE_INTERRUPT,
    CAUSE_TARGET,
    CAUSE_TRANSFER,
    COMPETING_CAUSES,
    PROTECTED_REASONS,
    STATUS_INTERRUPT,
    STATUS_ONGOING,
    STATUS_TRANSFER,
    TARGET_ACHIEVEMENT,
    Achievement,
    Enrollment,
)


@dataclass(frozen=True)
class Observation:
    """一名学员在一个起点队列中的观察记录（单位：天，自起点进入起算）。"""
    student_id: str
    time_days: int
    label: str                 # 竞争结局之一或 CENSORED
    reason: str                # 原始业务原因，便于审计
    matured: bool              # 观察窗是否完整（起点后满 horizon_days 仍无事件）
    subgroup: str              # 路径分组标签
    path_courses: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CohortCoverage:
    origin_course: str
    intake_start: object
    intake_end: object
    cutoff: object
    horizon_days: int
    eligible: Tuple[str, ...]
    excluded_late: Tuple[str, ...]      # 起点进入晚于招生窗口
    excluded_insufficient: Tuple[str, ...]  # 起点太晚、观察窗不完整
    protected_censored: Tuple[str, ...]     # 健康/时间安排退出
    ongoing_at_cutoff: Tuple[str, ...]      # 观察结束仍在学
    event_counts: Dict[str, int]


def _origin_entry(enrollments_by_student, origin_course):
    """返回学员在起点课程的最早注册；未修读起点课程返回 None。"""
    matches = [enr for enr in enrollments_by_student if enr.course_id == origin_course]
    if not matches:
        return None
    return min(matches, key=lambda enr: enr.entry_date)


def _first_target(achievements: Sequence[Achievement], student_id: str, after_day):
    candidates = [
        a.confirm_date for a in achievements
        if a.student_id == student_id
        and a.achievement_code == TARGET_ACHIEVEMENT
        and a.confirm_date >= after_day
    ]
    return min(candidates) if candidates else None


def build_cohort(origin_course, intake_start, intake_end, cutoff, horizon_days,
                 enrollments, achievements):
    """构造一个明确起点的竞争结局队列。

    ``enrollments`` 为全部注册记录，函数内部按学员聚合。事件日超出
    ``cutoff`` 或观察窗末日的，按删失处理，绝不使用推荐日之后才可得的信息。
    """
    by_student: Dict[str, List[Enrollment]] = {}
    for enr in enrollments:
        by_student.setdefault(enr.student_id, []).append(enr)

    eligible, excluded_late, excluded_insufficient = [], [], []
    protected, ongoing = [], []
    observations: List[Observation] = []
    counts = {cause: 0 for cause in COMPETING_CAUSES}
    counts[CENSORED] = 0

    for student_id in sorted(by_student):
        records = by_student[student_id]
        origin = _origin_entry(records, origin_course)
        if origin is None:
            continue
        if not (intake_start <= origin.entry_date <= intake_end):
            excluded_late.append(student_id)
            continue
        window_end = min(cutoff, origin.entry_date + timedelta(days=horizon_days))
        if (cutoff - origin.entry_date).days < horizon_days:
            excluded_insufficient.append(student_id)
            continue
        eligible.append(student_id)

        subgroup, path_courses = _classify_path(origin.entry_date, records)
        events: List[Tuple[int, str, str]] = []

        target_day = _first_target(achievements, student_id, origin.entry_date)
        if target_day is not None:
            events.append(((target_day - origin.entry_date).days, CAUSE_TARGET, "作品确认"))
        for enr in records:
            # 任意注册（含后续课程）在起点之后的退出都可能构成竞争事件：
            # 后续课程的转课/中断同样是从起点路径观察到的结局。
            if enr.exit_date is None or enr.exit_date < origin.entry_date:
                continue
            day = (enr.exit_date - origin.entry_date).days
            if enr.exit_status == STATUS_TRANSFER:
                events.append((day, CAUSE_TRANSFER, enr.exit_reason or "转课"))
            elif enr.exit_status == STATUS_INTERRUPT:
                if enr.exit_reason in PROTECTED_REASONS:
                    events.append((day, CENSORED, enr.exit_reason))
                else:
                    events.append((day, CAUSE_INTERRUPT, enr.exit_reason or "中断"))

        inside = [(d, label, reason) for d, label, reason in events
                  if origin.entry_date + timedelta(days=d) <= window_end]
        matured = (cutoff - origin.entry_date).days >= horizon_days
        if inside:
            first_day, label, reason = min(inside, key=lambda item: item[0])
            time_days = first_day
        else:
            label, reason, time_days = CENSORED, "观察窗内无事件", (window_end - origin.entry_date).days
        observations.append(Observation(
            student_id=student_id, time_days=time_days, label=label, reason=reason,
            matured=matured, subgroup=subgroup, path_courses=tuple(path_courses),
        ))
        counts[label] += 1
        if reason in PROTECTED_REASONS:
            protected.append(student_id)
        if any(enr.exit_date is None and enr.course_id == origin_course for enr in records) \
                and label == CENSORED:
            ongoing.append(student_id)

    coverage = CohortCoverage(
        origin_course=origin_course, intake_start=intake_start, intake_end=intake_end,
        cutoff=cutoff, horizon_days=horizon_days,
        eligible=tuple(eligible), excluded_late=tuple(excluded_late),
        excluded_insufficient=tuple(excluded_insufficient),
        protected_censored=tuple(protected), ongoing_at_cutoff=tuple(ongoing),
        event_counts=counts,
    )
    return observations, coverage


def _classify_path(origin_day, records: Sequence[Enrollment]):
    """给出路径分组与有序课程链；并行修读单独标注，不虚构先后。"""
    ordered = sorted(records, key=lambda enr: (enr.entry_date, enr.course_id))
    course_ids = [enr.course_id for enr in ordered]
    overlap = any(
        left.entry_date < (right.exit_date or left.entry_date)
        and right.entry_date < (left.exit_date or right.entry_date)
        and left is not right
        for i, left in enumerate(ordered) for right in ordered[i + 1:]
    )
    if len(course_ids) == 1:
        subgroup = "仅起点课程"
    elif overlap:
        subgroup = "并行修读（先后不可区分）"
    else:
        subgroup = "顺序进入后续课程"
    return subgroup, tuple(course_ids)
