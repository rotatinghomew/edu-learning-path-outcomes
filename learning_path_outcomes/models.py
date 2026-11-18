"""领域对象与口径常量。

所有记录均为本地合成数据，不含个人信息。日期统一使用 :class:`datetime.date`，
口径常量集中在此处，便于教务核对统计定义。
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional

# 注册记录的离开状态
STATUS_ONGOING = "在学"          # 观察结束仍在学习
STATUS_COMPLETED = "完成作品"    # 课程层面完成，是否算目标成果以成果确认为准
STATUS_TRANSFER = "转课"         # 转入其他路径
STATUS_INTERRUPT = "中断"        # 中断学习

# 受保护的退出原因：这类退出按删失处理，不算普通未完成
PROTECTED_REASONS = ("健康", "时间安排")

# 已确认成果代码：社区作品入选确认
TARGET_ACHIEVEMENT = "WORK"

# 竞争结局与删失标签
CAUSE_TARGET = "目标成果"
CAUSE_TRANSFER = "转入其他路径"
CAUSE_INTERRUPT = "中断"
CENSORED = "删失"

COMPETING_CAUSES = (CAUSE_TARGET, CAUSE_TRANSFER, CAUSE_INTERRUPT)


@dataclass(frozen=True)
class Course:
    course_id: str
    name: str
    level: str
    offer_start: date
    offer_end: Optional[date]
    prereq_achievement: Optional[str]


@dataclass(frozen=True)
class Enrollment:
    student_id: str
    course_id: str
    entry_date: date
    exit_date: Optional[date]
    exit_status: str
    exit_reason: str


@dataclass(frozen=True)
class Achievement:
    student_id: str
    achievement_code: str
    confirm_date: date
