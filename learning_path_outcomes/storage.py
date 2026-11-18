import sqlite3

from .recommendations import Recommendation


def replace_records(path, rows):
    """旧式聚合观察记录的临时存储（保留兼容）。"""
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS observations "
                           "(period TEXT, group_name TEXT, count INTEGER, value REAL)")
        connection.execute("DELETE FROM observations")
        connection.executemany("INSERT INTO observations VALUES (?, ?, ?, ?)",
                               [(row["period"], row["group"], int(row["count"]), float(row["value"]))
                                for row in rows])
        return connection.execute(
            "SELECT period, group_name, count, value FROM observations "
            "ORDER BY period, group_name").fetchall()


def replace_learning_records(path, courses, enrollments, achievements):
    """把学员级履历写入临时库，原始 CSV 不变。"""
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS courses ("
                           "course_id TEXT PRIMARY KEY, name TEXT, level TEXT, "
                           "offer_start TEXT, offer_end TEXT, prereq_achievement TEXT)")
        connection.execute("CREATE TABLE IF NOT EXISTS enrollments ("
                           "student_id TEXT, course_id TEXT, entry_date TEXT, "
                           "exit_date TEXT, exit_status TEXT, exit_reason TEXT)")
        connection.execute("CREATE TABLE IF NOT EXISTS achievements ("
                           "student_id TEXT, achievement_code TEXT, confirm_date TEXT)")
        for table in ("courses", "enrollments", "achievements"):
            connection.execute(f"DELETE FROM {table}")
        connection.executemany(
            "INSERT INTO courses VALUES (?, ?, ?, ?, ?, ?)",
            [(c.course_id, c.name, c.level, c.offer_start.isoformat(),
              c.offer_end.isoformat() if c.offer_end else None, c.prereq_achievement)
             for c in courses])
        connection.executemany(
            "INSERT INTO enrollments VALUES (?, ?, ?, ?, ?, ?)",
            [(e.student_id, e.course_id, e.entry_date.isoformat(),
              e.exit_date.isoformat() if e.exit_date else None,
              e.exit_status, e.exit_reason) for e in enrollments])
        connection.executemany(
            "INSERT INTO achievements VALUES (?, ?, ?)",
            [(a.student_id, a.achievement_code, a.confirm_date.isoformat())
             for a in achievements])


def save_recommendation(path, recommendation: Recommendation) -> int:
    """只追加保存推荐快照；历史快照永不更新或删除。"""
    import json
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS recommendation_snapshots ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, "
            "student_id TEXT, as_of TEXT, target_course_id TEXT, decision TEXT, "
            "eligible INTEGER, evidence_origin TEXT, gate_passed INTEGER, "
            "observation_window TEXT, candidate_courses TEXT, outcome_definition TEXT, "
            "reasons TEXT, association_only INTEGER, record_fingerprint TEXT, "
            "path_group TEXT)")
        cur = connection.execute(
            "INSERT INTO recommendation_snapshots ("
            "student_id, as_of, target_course_id, decision, eligible, evidence_origin, "
            "gate_passed, observation_window, candidate_courses, outcome_definition, "
            "reasons, association_only, record_fingerprint, path_group) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (recommendation.student_id, recommendation.as_of.isoformat(),
             recommendation.target_course_id, recommendation.decision,
             int(recommendation.eligible), recommendation.evidence_origin,
             None if recommendation.gate_passed is None else int(recommendation.gate_passed),
             json.dumps(recommendation.observation_window, ensure_ascii=False),
             json.dumps(list(recommendation.candidate_courses), ensure_ascii=False),
             json.dumps(recommendation.outcome_definition, ensure_ascii=False),
             json.dumps(list(recommendation.reasons), ensure_ascii=False),
             int(recommendation.association_only), recommendation.record_fingerprint,
             recommendation.path_group))
        return cur.lastrowid


def list_recommendations(path):
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT id, student_id, as_of, target_course_id, decision, "
            "record_fingerprint FROM recommendation_snapshots ORDER BY id").fetchall()
