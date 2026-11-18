"""进阶推荐：点-in-time 证据应用与不可变快照。

规则（对应教务需求）：
1. 只使用推荐日 ``as_of`` 已经可得的注册与成果记录；之后才产生的完成记录
   不参与推荐，因此过去推荐的理由不会被后续数据改写。
2. 先修资格只按已确认成果判断，课程注册或"完成课程"状态本身不授予资格。
3. 证据必须同时通过规模/随访门槛、人群可比性和时间顺序可区分性；
   任一项不满足即显示证据不足，不用全体平均补齐。
4. 快照记录观察窗口、可选课程、结果定义与记录指纹，写入后只追加不改写。
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Dict, Optional, Sequence, Tuple

from .models import Achievement, Course, Enrollment
from .paths import PathEvidence, evaluate_origin


@dataclass(frozen=True)
class Recommendation:
    student_id: str
    as_of: date
    target_course_id: Optional[str]
    decision: str                       # 可推荐 / 证据不足 / 不符合先修资格 / 无适配课程
    eligible: bool
    evidence_origin: Optional[str]
    gate_passed: Optional[bool]
    observation_window: Dict[str, object]
    candidate_courses: Tuple[str, ...]
    outcome_definition: Dict[str, object]
    reasons: Tuple[str, ...]
    association_only: bool
    record_fingerprint: str
    path_group: Optional[str] = None


def as_of_view(as_of: date, enrollments: Sequence[Enrollment],
               achievements: Sequence[Achievement]):
    """截断到推荐日：推荐日之后的进入、离开与成果确认全部不可见。"""
    visible_enrollments = [
        Enrollment(
            student_id=e.student_id, course_id=e.course_id, entry_date=e.entry_date,
            exit_date=e.exit_date if e.exit_date is not None and e.exit_date <= as_of else None,
            exit_status=e.exit_status if e.exit_date is not None and e.exit_date <= as_of else "在学",
            exit_reason=e.exit_reason if e.exit_date is not None and e.exit_date <= as_of else "",
        )
        for e in enrollments if e.entry_date <= as_of
    ]
    visible_achievements = [a for a in achievements if a.confirm_date <= as_of]
    return visible_enrollments, visible_achievements


def has_confirmed_achievement(student_id: str, code: str,
                              achievements: Sequence[Achievement]) -> bool:
    """先修资格判定：只认真实确认的成果。"""
    return any(a.student_id == student_id and a.achievement_code == code
               for a in achievements)


def _fingerprint(enrollments: Sequence[Enrollment],
                 achievements: Sequence[Achievement]) -> str:
    payload = {
        "enrollments": sorted(
            (e.student_id, e.course_id, e.entry_date.isoformat(),
             e.exit_date.isoformat() if e.exit_date else None,
             e.exit_status, e.exit_reason) for e in enrollments),
        "achievements": sorted(
            (a.student_id, a.achievement_code, a.confirm_date.isoformat())
            for a in achievements),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _student_origin(enrollments: Sequence[Enrollment], student_id: str) -> Optional[str]:
    mine = [e for e in enrollments if e.student_id == student_id]
    if not mine:
        return None
    return min(mine, key=lambda e: e.entry_date).course_id


def _student_path_group(evidence: PathEvidence, student_id: str) -> Optional[str]:
    for group in evidence.path_groups:
        if student_id in group.members:
            return group.name
    return None


def recommend(student_id: str, as_of: date, courses: Sequence[Course],
              enrollments: Sequence[Enrollment], achievements: Sequence[Achievement],
              intake_start: date, intake_end: date, horizon_days: int,
              min_cohort: int = 8, min_matured: int = 3,
              replicates: int = 200) -> Recommendation:
    visible_enrollments, visible_achievements = as_of_view(as_of, enrollments, achievements)
    fingerprint = _fingerprint(visible_enrollments, visible_achievements)

    candidates = tuple(c.course_id for c in courses
                       if c.level == "进阶" and c.offer_start <= as_of)
    target = next((c for c in courses if c.course_id in candidates), None)
    window = {
        "intake_start": intake_start.isoformat(),
        "intake_end": intake_end.isoformat(),
        "as_of": as_of.isoformat(),
        "horizon_days": horizon_days,
        "time_origin": "起点课程实际进入日（各人第0天）",
    }
    outcome_definition = {
        "competing_outcomes": ["目标成果", "转入其他路径", "中断"],
        "target": "已确认的社区作品成果（WORK），以确认日为准",
        "censoring": ["观察结束仍在学", "健康原因退出", "时间安排原因退出", "观察窗后事件"],
        "first_event_only": True,
        "interpretation": "关联证据，不得解释为课程因果效应",
    }
    base = dict(as_of=as_of, observation_window=window, candidate_courses=candidates,
                outcome_definition=outcome_definition, record_fingerprint=fingerprint,
                association_only=True)

    origin = _student_origin(visible_enrollments, student_id)
    if target is None:
        return Recommendation(
            student_id=student_id, target_course_id=None,
            decision="无适配课程", eligible=False, evidence_origin=origin,
            gate_passed=None, reasons=("推荐日没有已开课的进阶候选课程",),
            path_group=None, **base)

    if not has_confirmed_achievement(student_id, target.prereq_achievement,
                                     visible_achievements):
        return Recommendation(
            student_id=student_id, target_course_id=target.course_id,
            decision="不符合先修资格", eligible=False, evidence_origin=origin,
            gate_passed=None,
            reasons=(f"未见已确认的先修成果 {target.prereq_achievement}；"
                     "注册状态与课程完成不授予资格",),
            path_group=None, **base)

    if origin is None:
        return Recommendation(
            student_id=student_id, target_course_id=target.course_id,
            decision="证据不足", eligible=True, evidence_origin=None,
            gate_passed=False, reasons=("学员在推荐日没有可见的起点课程经历",),
            path_group=None, **base)

    evidence, coverage = evaluate_origin(
        origin, intake_start, intake_end, as_of, horizon_days,
        visible_enrollments, visible_achievements,
        min_cohort=min_cohort, min_matured=min_matured, replicates=replicates)
    group_name = _student_path_group(evidence, student_id)
    reasons = list(evidence.gate.reasons)

    # 可比性：学员必须属于证据队列覆盖的起点人群与招生窗口
    if student_id not in coverage.eligible:
        why = ("学员不在证据队列覆盖范围内（起点进入晚于招生窗口或随访不完整），"
               "与证据人群不具可比性")
        reasons.append(why)
    # 时间顺序可区分性：并行修读不生成顺序路径证据
    ordering_ok = True
    for group in evidence.path_groups:
        if student_id in group.members and not group.ordering_distinguishable:
            ordering_ok = False
            reasons.append(f"{group.name}：{group.note}")

    if not evidence.gate.passed or student_id not in coverage.eligible or not ordering_ok:
        return Recommendation(
            student_id=student_id, target_course_id=target.course_id,
            decision="证据不足", eligible=True, evidence_origin=origin,
            gate_passed=evidence.gate.passed, reasons=tuple(reasons),
            path_group=group_name, **base)

    support = (
        f"同一起点 {origin} 的 {evidence.cohort_size} 人队列在 {horizon_days} 天观察窗内，"
        f"目标成果累积发生概率 {evidence.overall_cif['目标成果']:.1%}"
        f"（自助95%区间 {evidence.overall_ci['目标成果'][0]:.1%}–"
        f"{evidence.overall_ci['目标成果'][1]:.1%}）；该路径与学员所在"
        f"「{group_name}」人群可比，且时间顺序可区分。证据仅为关联，不构成收益承诺。"
    )
    return Recommendation(
        student_id=student_id, target_course_id=target.course_id,
        decision="可推荐", eligible=True, evidence_origin=origin,
        gate_passed=True, reasons=(support,), path_group=group_name, **base)
