"""路径分析报告入口：从学员级履历到运营摘要与推荐快照。

运行：python3 -m learning_path_outcomes.path_report
所有数据均为本地合成数据，SQLite 临时库随用随建，原始 CSV 不变。
"""
import tempfile
from datetime import date
from pathlib import Path

from .models import COMPETING_CAUSES
from .paths import evaluate_origin
from .records import read_achievements, read_courses, read_enrollments
from .recommendations import recommend
from .storage import replace_learning_records, save_recommendation

DATA_DIR = Path(__file__).parent.parent / "data"
INTAKE_START = date(2025, 2, 10)
INTAKE_END = date(2025, 3, 31)
CUTOFF = date(2026, 9, 30)
HORIZON_DAYS = 180


def _print_coverage(coverage):
    print(f"\n【覆盖与不确定性】起点 {coverage.origin_course}")
    print(f"  招生窗口 {coverage.intake_start} ~ {coverage.intake_end}，"
          f"截止 {coverage.cutoff}，观察窗 {coverage.horizon_days} 天")
    print(f"  纳入风险集合 {len(coverage.eligible)} 人：{', '.join(coverage.eligible)}")
    print(f"  窗口外晚到 {len(coverage.excluded_late)} 人："
          f"{', '.join(coverage.excluded_late) or '无'}")
    print(f"  随访不足剔除 {len(coverage.excluded_insufficient)} 人："
          f"{', '.join(coverage.excluded_insufficient) or '无'}")
    print(f"  受保护删失（健康/时间安排）：{', '.join(coverage.protected_censored) or '无'}；"
          f"观察结束仍在学：{', '.join(coverage.ongoing_at_cutoff) or '无'}")
    print("  首事件计数：" + "，".join(f"{cause} {coverage.event_counts[cause]} 人"
                                    for cause in (*COMPETING_CAUSES, "删失")))


def main():
    courses = read_courses(DATA_DIR / "courses.csv")
    enrollments = read_enrollments(DATA_DIR / "enrollments.csv")
    achievements = read_achievements(DATA_DIR / "achievements.csv")

    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "learning.db"
        replace_learning_records(db_path, courses, enrollments, achievements)

        print("=" * 72)
        print("进阶路径证据（竞争结局：目标成果 / 转入其他路径 / 中断，其余为删失）")
        print("=" * 72)
        for origin in ("P100", "X100"):
            evidence, coverage = evaluate_origin(
                origin, INTAKE_START, INTAKE_END, CUTOFF, HORIZON_DAYS,
                enrollments, achievements)
            _print_coverage(coverage)
            print(f"  队列规模 {evidence.cohort_size} 人，完整随访 {evidence.matured} 人；"
                  f"证据门槛：{'通过' if evidence.gate.passed else '未通过'}")
            for reason in evidence.gate.reasons:
                print(f"    - {reason}")
            for cause in COMPETING_CAUSES:
                low, high = evidence.overall_ci[cause]
                print(f"  {cause}：{evidence.overall_cif[cause]:.1%} "
                      f"（自助95%区间 {low:.1%}–{high:.1%}）")
            for group in evidence.path_groups:
                cif = evidence.group_cif[group.name]
                tag = "" if group.ordering_distinguishable else " —— 顺序不可区分，不作路径推荐依据"
                print(f"  分组「{group.name}」{len(group.members)} 人{tag}："
                      + "，".join(f"{cause} {cif[cause]:.1%}" for cause in COMPETING_CAUSES))
            ws = evidence.waiting_days_summary
            if ws["n"]:
                print(f"  进入后续课程前等待：{ws['n']} 人次，平均 {ws['mean_days']:.0f} 天，"
                      f"最长 {ws['max_days']} 天（不计入后续课程经验）")
            for caveat in evidence.caveats:
                print(f"  口径说明：{caveat}")

        print("\n" + "=" * 72)
        print("点-in-time 推荐演示（只用推荐日可得记录）")
        print("=" * 72)
        demo_as_of = date(2026, 9, 30)
        for student_id in ("S06", "S15", "S13", "S05", "S14"):
            rec = recommend(student_id, demo_as_of, courses, enrollments, achievements,
                            INTAKE_START, INTAKE_END, HORIZON_DAYS)
            print(f"\n学员 {student_id} → {rec.target_course_id or '无候选'}：{rec.decision}")
            print(f"  观察窗口：{rec.observation_window}")
            print(f"  可选课程：{list(rec.candidate_courses) or '无'}")
            print(f"  结果定义：{rec.outcome_definition['competing_outcomes']}，"
                  f"删失={rec.outcome_definition['censoring']}")
            for reason in rec.reasons:
                print(f"  理由：{reason}")
            snapshot_id = save_recommendation(db_path, rec)
            print(f"  快照 #{snapshot_id} 已只追加保存，指纹 {rec.record_fingerprint[:12]}…")

        # 不可变性核对：同一学员在更早的推荐日生成快照，后来的完成记录不改变旧快照
        early = recommend("S08", date(2025, 9, 1), courses, enrollments, achievements,
                          INTAKE_START, INTAKE_END, HORIZON_DAYS)
        early_id = save_recommendation(db_path, early)
        print(f"\n不可变性核对：S08 于 2025-09-01 的推荐为「{early.decision}」，"
              f"快照 #{early_id}（其作品 2025-10-20 才确认，当时不可见）")
        for row in __import__("learning_path_outcomes.storage", fromlist=["list_recommendations"]
                              ).list_recommendations(db_path):
            print("  库存快照：", row)


if __name__ == "__main__":
    main()
