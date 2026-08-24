"""Copy the local CareerFit SQLite database into an empty Supabase database."""

import argparse
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from psycopg import OperationalError, connect, sql


ROOT = Path(__file__).resolve().parents[1]
TABLES = (
    "accounts",
    "users",
    "profiles",
    "uploaded_files",
    "experiences",
    "experience_versions",
    "source_facts",
    "experience_sources",
    "experience_corrections",
    "experience_preferences",
    "job_profiles",
    "personal_materials",
    "job_descriptions",
    "job_skills",
    "essay_questions",
    "experience_match_results",
    "recommendation_ground_truth",
    "essay_outlines",
    "essay_drafts",
    "fact_check_results",
    "ai_call_logs",
    "embeddings",
)
ID_TABLES = tuple(table for table in TABLES if table != "experience_sources")


def _postgres_value(value):
    return value.replace("\x00", "") if isinstance(value, str) else value


def _rows(source: sqlite3.Connection, table: str) -> tuple[list[str], list[tuple]]:
    result = source.execute(f'SELECT * FROM "{table}"')
    columns = [item[0] for item in result.description]
    return columns, [tuple(_postgres_value(value) for value in row) for row in result.fetchall()]


def migrate(source_path: Path, database_url: str) -> dict[str, int]:
    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    counts: dict[str, int] = {}
    try:
        with connect(database_url, prepare_threshold=None) as target:
            target.execute((ROOT / "schema_postgres.sql").read_text(encoding="utf-8"), prepare=False)
            occupied = target.execute(
                "SELECT (SELECT COUNT(*) FROM accounts) + "
                "(SELECT COUNT(*) FROM experiences) + (SELECT COUNT(*) FROM job_descriptions)"
            ).fetchone()[0]
            if occupied:
                raise RuntimeError("Supabase DB가 비어 있지 않아 복사를 중단했습니다.")

            target.execute("DELETE FROM users WHERE account_id IS NULL")
            current_versions: list[tuple[int, int]] = []
            for table in TABLES:
                columns, rows = _rows(source, table)
                if table == "experiences":
                    version_index = columns.index("current_version_id")
                    id_index = columns.index("id")
                    current_versions = [
                        (row[version_index], row[id_index]) for row in rows if row[version_index] is not None
                    ]
                    rows = [tuple(None if i == version_index else value for i, value in enumerate(row)) for row in rows]
                if rows:
                    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                        sql.Identifier(table),
                        sql.SQL(", ").join(map(sql.Identifier, columns)),
                        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                    )
                    target.cursor().executemany(statement, rows)
                counts[table] = len(rows)

            if current_versions:
                target.cursor().executemany(
                    "UPDATE experiences SET current_version_id=%s WHERE id=%s", current_versions
                )
            for table in ID_TABLES:
                target.execute(
                    sql.SQL(
                        "SELECT setval(pg_get_serial_sequence({table}, 'id'), "
                        "GREATEST((SELECT COALESCE(MAX(id), 1) FROM {identifier}), 1), true)"
                    ).format(table=sql.Literal(table), identifier=sql.Identifier(table))
                )
    finally:
        source.close()
    return counts


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data" / "careerfit.db")
    args = parser.parse_args()
    database_url = os.getenv("SUPABASE_DB_URL", "")
    if not database_url:
        raise SystemExit(".env에 SUPABASE_DB_URL을 먼저 설정하세요.")
    if not args.source.is_file():
        raise SystemExit(f"SQLite 파일을 찾을 수 없습니다: {args.source}")
    try:
        counts = migrate(args.source, database_url)
    except OperationalError as exc:
        if "password authentication failed" in str(exc):
            raise SystemExit(
                "Supabase DB 비밀번호가 맞지 않습니다. 프로젝트의 Database password를 재설정한 뒤 "
                ".env의 SUPABASE_DB_URL을 갱신하세요."
            ) from None
        raise
    print("Supabase 복사 완료:", ", ".join(f"{name}={count}" for name, count in counts.items()))


if __name__ == "__main__":
    main()
