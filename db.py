import atexit
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date
from typing import Any, Iterator

from config import BASE_DIR, DATABASE_URL, DB_PATH
from models import (
    EssayOutline,
    ExperienceData,
    ExperiencePreference,
    FactCheckItem,
    JDAnalysis,
    PersonalMaterial,
    ProfileData,
    QuestionAnalysis,
)


APPLICATION_STATUSES = (
    "관심",
    "준비 중",
    "작성 중",
    "제출 완료",
    "서류 합격",
    "면접 진행",
    "최종 합격",
    "불합격",
    "보류",
)

_POSTGRES_POOL = None
_POSTGRES_POOL_URL = ""
_POSTGRES_POOL_LOCK = threading.Lock()


def _close_postgres_pool() -> None:
    if _POSTGRES_POOL is not None and not _POSTGRES_POOL.closed:
        _POSTGRES_POOL.close()


atexit.register(_close_postgres_pool)


def init_db() -> None:
    if DATABASE_URL:
        with connect() as conn:
            conn.executescript((BASE_DIR / "schema_postgres.sql").read_text(encoding="utf-8"))
            conn.execute("INSERT OR IGNORE INTO users(id, display_name) VALUES (1, '프로필 1')")
            conn.execute(
                "SELECT setval(pg_get_serial_sequence('users', 'id'), "
                "GREATEST((SELECT COALESCE(MAX(id), 1) FROM users), 1), true)"
            )
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript((BASE_DIR / "schema.sql").read_text(encoding="utf-8"))
        _add_account_owner_column(conn)
        _allow_personal_material_outlines(conn)
        _add_application_tracking_columns(conn)
        conn.execute("INSERT OR IGNORE INTO users(id, display_name) VALUES (1, '프로필 1')")
        conn.execute(
            """UPDATE users SET display_name=COALESCE(
                   NULLIF((SELECT nickname FROM profiles WHERE user_id=1), ''), '프로필 1')
               WHERE id=1 AND display_name='나'"""
        )


def _add_account_owner_column(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "account_id" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN account_id INTEGER REFERENCES accounts(id)")


def _allow_personal_material_outlines(conn: sqlite3.Connection) -> None:
    experience_column = next(
        (row for row in conn.execute("PRAGMA table_info(essay_outlines)") if row["name"] == "experience_id"),
        None,
    )
    if not experience_column or not experience_column["notnull"]:
        return
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(
        """
        CREATE TABLE essay_outlines_new (
            id INTEGER PRIMARY KEY,
            essay_question_id INTEGER NOT NULL REFERENCES essay_questions(id) ON DELETE CASCADE,
            experience_id INTEGER REFERENCES experiences(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            outline_json TEXT NOT NULL,
            is_approved INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO essay_outlines_new
            (id, essay_question_id, experience_id, version_number, outline_json, is_approved, created_at)
        SELECT id, essay_question_id, experience_id, version_number, outline_json, is_approved, created_at
        FROM essay_outlines;
        DROP TABLE essay_outlines;
        ALTER TABLE essay_outlines_new RENAME TO essay_outlines;
        CREATE INDEX IF NOT EXISTS idx_essay_outlines_question
            ON essay_outlines(essay_question_id, version_number DESC);
        """
    )
    conn.execute("PRAGMA foreign_keys = ON")


def _add_application_tracking_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(job_descriptions)")}
    for name, definition in {
        "application_status": "TEXT NOT NULL DEFAULT '관심'",
        "deadline": "TEXT NOT NULL DEFAULT ''",
        "application_memo": "TEXT NOT NULL DEFAULT ''",
    }.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE job_descriptions ADD COLUMN {name} {definition}")


class _PostgresRow(dict):
    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class _PostgresCursor:
    def __init__(self, cursor: Any):
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def fetchone(self) -> _PostgresRow | None:
        row = self._cursor.fetchone()
        return _PostgresRow(row) if row is not None else None

    def fetchall(self) -> list[_PostgresRow]:
        return [_PostgresRow(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        return (_PostgresRow(row) for row in self._cursor)


class _PostgresConnection:
    def __init__(self, connection: Any):
        self._connection = connection

    def execute(self, sql: str, params: Any = ()) -> _PostgresCursor:
        return _PostgresCursor(self._connection.execute(_postgres_sql(sql), params))

    def executemany(self, sql: str, params: Any) -> _PostgresCursor:
        cursor = self._connection.cursor()
        cursor.executemany(_postgres_sql(sql), params)
        return _PostgresCursor(cursor)

    def executescript(self, sql: str) -> None:
        self._connection.execute(sql, prepare=False)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


def _postgres_sql(sql: str) -> str:
    statement = sql.strip().rstrip(";")
    ignore_conflict = bool(re.match(r"INSERT\s+OR\s+IGNORE\s+INTO", statement, re.IGNORECASE))
    statement = re.sub(
        r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", statement, count=1, flags=re.IGNORECASE
    )
    statement = statement.replace(
        "json_extract(v.profile_json, '$.confidence')",
        "((v.profile_json::jsonb ->> 'confidence')::double precision)",
    ).replace(
        "GROUP_CONCAT(DISTINCT js.skill_type)",
        "STRING_AGG(DISTINCT js.skill_type, ',')",
    ).replace(
        "ROUND(AVG(js.importance), 2)",
        "ROUND(AVG(js.importance)::numeric, 2)::double precision",
    ).replace(
        "SELECT js.skill_name, STRING_AGG",
        "SELECT MIN(js.skill_name) AS skill_name, STRING_AGG",
    ).replace(
        "average_importance DESC, js.skill_name",
        "average_importance DESC, skill_name",
    )
    statement = statement.replace("?", "%s")
    if ignore_conflict and " ON CONFLICT " not in statement.upper():
        statement += " ON CONFLICT DO NOTHING"
    return statement


def _is_unique_violation(exc: Exception) -> bool:
    return isinstance(exc, sqlite3.IntegrityError) or getattr(exc, "sqlstate", None) == "23505"


def _get_postgres_pool():
    global _POSTGRES_POOL, _POSTGRES_POOL_URL
    if _POSTGRES_POOL is not None and _POSTGRES_POOL_URL == DATABASE_URL:
        return _POSTGRES_POOL
    with _POSTGRES_POOL_LOCK:
        if _POSTGRES_POOL is not None and _POSTGRES_POOL_URL != DATABASE_URL:
            _POSTGRES_POOL.close()
            _POSTGRES_POOL = None
        if _POSTGRES_POOL is None:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            _POSTGRES_POOL = ConnectionPool(
                DATABASE_URL,
                min_size=1,
                max_size=5,
                max_idle=300,
                timeout=15,
                kwargs={"row_factory": dict_row, "prepare_threshold": None},
                open=True,
            )
            _POSTGRES_POOL_URL = DATABASE_URL
    return _POSTGRES_POOL


def _insert_id(conn: Any, sql: str, params: Any) -> int:
    if DATABASE_URL:
        row = conn.execute(f"{sql.rstrip().rstrip(';')} RETURNING id", params).fetchone()
        return int(row["id"])
    return int(conn.execute(sql, params).lastrowid)


@contextmanager
def connect() -> Iterator[Any]:
    if DATABASE_URL:
        try:
            pool = _get_postgres_pool()
        except ImportError as exc:
            raise RuntimeError("Supabase 연결에는 psycopg pool 패키지가 필요합니다.") from exc
        with pool.connection() as raw:
            conn = _PostgresConnection(raw)
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def save_profile(profile: ProfileData, user_id: int = 1) -> None:
    values = profile.model_dump()
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    updates = ", ".join(f"{key}=excluded.{key}" for key in values)
    with connect() as conn:
        conn.execute(
            f"""INSERT INTO profiles(user_id, {columns}) VALUES (?, {placeholders})
                ON CONFLICT(user_id) DO UPDATE SET {updates}, updated_at=CURRENT_TIMESTAMP""",
            [user_id, *values.values()],
        )
        if profile.nickname.strip():
            conn.execute("UPDATE users SET display_name=? WHERE id=?", (profile.nickname.strip(), user_id))


def list_users(account_id: int | None = None) -> list[dict]:
    with connect() as conn:
        where = "WHERE u.account_id=?" if account_id is not None else ""
        rows = conn.execute(
            f"""SELECT u.id, u.display_name, u.created_at,
                      COUNT(DISTINCT e.id) AS experience_count,
                      COUNT(DISTINCT jd.id) AS jd_count
               FROM users u
               LEFT JOIN experiences e ON e.user_id=u.id
               LEFT JOIN job_descriptions jd ON jd.user_id=u.id
               {where}
               GROUP BY u.id ORDER BY u.id""",
            (account_id,) if account_id is not None else (),
        ).fetchall()
    return [dict(row) for row in rows]


def create_user(display_name: str, account_id: int | None = None) -> int:
    name = display_name.strip()
    if not name:
        raise ValueError("프로필 이름을 입력해 주세요.")
    if len(name) > 50:
        raise ValueError("프로필 이름은 50자 이하여야 합니다.")
    with connect() as conn:
        if account_id is not None and not conn.execute(
            "SELECT 1 FROM accounts WHERE id=?", (account_id,)
        ).fetchone():
            raise ValueError("로그인 계정을 찾을 수 없습니다.")
        user_id = _insert_id(
            conn,
            "INSERT INTO users(account_id, display_name) VALUES (?, ?)", (account_id, name)
        )
        conn.execute("INSERT INTO profiles(user_id, nickname) VALUES (?, ?)", (user_id, name))
        return user_id


def has_accounts() -> bool:
    with connect() as conn:
        return bool(conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone())


def get_account(account_id: int | None) -> dict | None:
    if account_id is None:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT id, email, display_name, created_at FROM accounts WHERE id=?", (account_id,)
        ).fetchone()
    return dict(row) if row else None


def register_account(email: str, password: str, display_name: str) -> int:
    normalized_email = _validate_email(email)
    name = display_name.strip()
    if not name:
        raise ValueError("이름을 입력해 주세요.")
    if len(name) > 50:
        raise ValueError("이름은 50자 이하여야 합니다.")
    _validate_password(password)
    password_hash = _hash_password(password)
    with connect() as conn:
        first_account = not conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone()
        try:
            account_id = _insert_id(
                conn,
                "INSERT INTO accounts(email, display_name, password_hash) VALUES (?, ?, ?)",
                (normalized_email, name, password_hash),
            )
        except Exception as exc:
            if not _is_unique_violation(exc):
                raise
            raise ValueError("이미 가입된 이메일입니다.") from exc
        if first_account:
            conn.execute("UPDATE users SET account_id=? WHERE account_id IS NULL", (account_id,))
        else:
            user_id = _insert_id(
                conn,
                "INSERT INTO users(account_id, display_name) VALUES (?, ?)",
                (account_id, "프로필 1"),
            )
            conn.execute("INSERT INTO profiles(user_id, nickname) VALUES (?, '프로필 1')", (user_id,))
        return account_id


def authenticate_account(email: str, password: str) -> dict | None:
    normalized_email = email.strip().casefold()
    with connect() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE email=?", (normalized_email,)).fetchone()
    if not row or not _verify_password(password, row["password_hash"]):
        return None
    return {key: row[key] for key in ("id", "email", "display_name", "created_at")}


def create_auth_session(account_id: int, ttl_seconds: int = 30 * 24 * 60 * 60) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = int(time.time())
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone():
            raise ValueError("로그인 계정을 찾을 수 없습니다.")
        conn.execute("DELETE FROM auth_sessions WHERE expires_at<=?", (now,))
        conn.execute(
            "INSERT INTO auth_sessions(account_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (account_id, token_hash, now + ttl_seconds),
        )
    return token


def authenticate_session(token: str | None) -> dict | None:
    if not token or len(token) > 128:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = int(time.time())
    with connect() as conn:
        row = conn.execute(
            """SELECT a.id, a.email, a.display_name, a.created_at
               FROM auth_sessions s JOIN accounts a ON a.id=s.account_id
               WHERE s.token_hash=? AND s.expires_at>?""",
            (token_hash, now),
        ).fetchone()
    return dict(row) if row else None


def revoke_auth_session(token: str | None) -> None:
    if not token:
        return
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with connect() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash,))


def _validate_email(email: str) -> str:
    normalized = email.strip().casefold()
    if len(normalized) > 254 or normalized.count("@") != 1 or not all(normalized.split("@")):
        raise ValueError("올바른 이메일을 입력해 주세요.")
    return normalized


def _validate_password(password: str) -> None:
    if len(password) < 6:
        raise ValueError("비밀번호는 6자 이상이어야 합니다.")
    if len(password) > 128:
        raise ValueError("비밀번호는 128자 이하여야 합니다.")


def _hash_password(password: str) -> str:
    iterations = 260_000
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"{iterations}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        iterations_text, salt_hex, digest_hex = encoded.split("$", 2)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations_text)
        )
        return hmac.compare_digest(actual, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


def get_profile(user_id: int = 1) -> ProfileData:
    with connect() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        return ProfileData()
    return ProfileData.model_validate({key: row[key] for key in ProfileData.model_fields})


def save_personal_material(
    material: PersonalMaterial, user_id: int = 1, material_id: int | None = None
) -> int:
    if not material.title.strip():
        raise ValueError("개인 소재 제목을 입력해 주세요.")
    values = material.model_dump()
    with connect() as conn:
        if material_id is None:
            return _insert_id(
                conn,
                f"INSERT INTO personal_materials(user_id, {', '.join(values)}) "
                f"VALUES (?, {', '.join('?' for _ in values)})",
                (user_id, *values.values()),
            )
        _require_personal_material_owner(conn, material_id, user_id)
        conn.execute(
            "UPDATE personal_materials SET "
            + ", ".join(f"{key}=?" for key in values)
            + ", updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (*values.values(), material_id),
        )
        return material_id


def list_personal_materials(user_id: int = 1) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM personal_materials WHERE user_id=? ORDER BY updated_at DESC, id DESC",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_personal_material(material_id: int, user_id: int = 1) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM personal_materials WHERE id=? AND user_id=?", (material_id, user_id)
        ).fetchone()
    return dict(row) if row else None


def delete_personal_material(material_id: int, user_id: int = 1) -> None:
    with connect() as conn:
        _require_personal_material_owner(conn, material_id, user_id)
        outlines = conn.execute(
            """SELECT o.id, o.outline_json FROM essay_outlines o
               JOIN essay_questions q ON q.id=o.essay_question_id
               JOIN job_descriptions jd ON jd.id=q.job_description_id
               WHERE jd.user_id=?""",
            (user_id,),
        ).fetchall()
        linked_ids = [
            row["id"]
            for row in outlines
            if material_id in json.loads(row["outline_json"]).get("material_ids", [])
        ]
        if linked_ids:
            conn.executemany("DELETE FROM essay_outlines WHERE id=?", [(item,) for item in linked_ids])
        conn.execute("DELETE FROM personal_materials WHERE id=?", (material_id,))


def add_uploaded_file(
    filename: str, file_type: str, content_hash: str, storage_path: str, extracted_text: str, user_id: int = 1
) -> tuple[int, bool]:
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM uploaded_files WHERE user_id=? AND content_hash=?", (user_id, content_hash)
        ).fetchone()
        if existing:
            return existing["id"], False
        uploaded_file_id = _insert_id(
            conn,
            """INSERT INTO uploaded_files(user_id, filename, file_type, content_hash, storage_path, extracted_text)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, filename, file_type, content_hash, storage_path, extracted_text),
        )
        return uploaded_file_id, True


def list_uploaded_files(user_id: int = 1) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, filename, file_type, uploaded_at, length(extracted_text) AS text_length "
            "FROM uploaded_files WHERE user_id=? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_uploaded_files(file_ids: list[int], user_id: int = 1) -> list[dict]:
    if not file_ids:
        return []
    placeholders = ",".join("?" for _ in file_ids)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM uploaded_files WHERE user_id=? AND id IN ({placeholders}) ORDER BY id",
            [user_id, *file_ids],
        ).fetchall()
    return [dict(row) for row in rows]


def create_experience(experience: ExperienceData, files: list[dict], user_id: int = 1) -> int:
    payload = experience.model_dump_json()
    with connect() as conn:
        experience_id = _insert_id(
            conn,
            "INSERT INTO experiences(user_id, experience_name) VALUES (?, ?)",
            (user_id, experience.experience_name or "이름 미확인 경험"),
        )
        version = _insert_id(
            conn,
            """INSERT INTO experience_versions
               (experience_id, version_number, profile_json, change_note, created_by)
               VALUES (?, 1, ?, 'AI 최초 추출', 'AI')""",
            (experience_id, payload),
        )
        conn.execute("UPDATE experiences SET current_version_id=? WHERE id=?", (version, experience_id))

        named_files = {file["filename"]: file for file in files}
        selected = [named_files[name] for name in experience.source_files if name in named_files] or files
        for file in selected:
            conn.execute(
                "INSERT OR IGNORE INTO experience_sources(experience_id, uploaded_file_id) VALUES (?, ?)",
                (experience_id, file["id"]),
            )
        for evidence in experience.evidence:
            file = named_files.get(evidence.source_file) or (selected[0] if selected else None)
            if file and evidence.quote.strip():
                conn.execute(
                    """INSERT INTO source_facts(experience_id, uploaded_file_id, fact_text, evidence_text)
                       VALUES (?, ?, ?, ?)""",
                    (experience_id, file["id"], evidence.quote.strip(), evidence.quote.strip()),
                )
        return experience_id


def list_experiences(user_id: int = 1) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT e.id, e.experience_name, e.review_status, e.updated_at,
                      v.version_number, json_extract(v.profile_json, '$.confidence') AS confidence
               FROM experiences e
               JOIN experience_versions v ON v.id=e.current_version_id
               WHERE e.user_id=? ORDER BY e.updated_at DESC, e.id DESC""",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_experience(experience_id: int, user_id: int = 1) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            """SELECT e.*, v.profile_json, v.version_number, v.is_approved
               FROM experiences e JOIN experience_versions v ON v.id=e.current_version_id
               WHERE e.id=? AND e.user_id=?""",
            (experience_id, user_id),
        ).fetchone()
        if not row:
            return None
        facts = conn.execute(
            """SELECT sf.id, sf.fact_text, sf.evidence_text, uf.filename
               FROM source_facts sf JOIN uploaded_files uf ON uf.id=sf.uploaded_file_id
               WHERE sf.experience_id=? ORDER BY sf.id""",
            (experience_id,),
        ).fetchall()
        versions = conn.execute(
            """SELECT id, version_number, profile_json, change_note, created_by, is_approved, created_at
               FROM experience_versions WHERE experience_id=? ORDER BY version_number DESC""",
            (experience_id,),
        ).fetchall()
        preferences = conn.execute(
            "SELECT * FROM experience_preferences WHERE experience_id=? ORDER BY target_role",
            (experience_id,),
        ).fetchall()
        corrections = conn.execute(
            "SELECT * FROM experience_corrections WHERE experience_id=? ORDER BY id DESC", (experience_id,)
        ).fetchall()
    result = dict(row)
    result["profile"] = json.loads(result.pop("profile_json"))
    result["facts"] = [dict(item) for item in facts]
    result["versions"] = [dict(item) | {"profile": json.loads(item["profile_json"])} for item in versions]
    result["preferences"] = [dict(item) for item in preferences]
    result["corrections"] = [dict(item) for item in corrections]
    return result


def delete_experience(experience_id: int, user_id: int = 1) -> None:
    with connect() as conn:
        _require_experience_owner(conn, experience_id, user_id)
        conn.execute("DELETE FROM experiences WHERE id=? AND user_id=?", (experience_id, user_id))


def get_preference(experience_id: int, target_role: str, user_id: int = 1) -> ExperiencePreference:
    with connect() as conn:
        row = conn.execute(
            """SELECT p.* FROM experience_preferences p
               JOIN experiences e ON e.id=p.experience_id
               WHERE p.experience_id=? AND p.target_role=? AND e.user_id=?""",
            (experience_id, target_role or "공통", user_id),
        ).fetchone()
    if not row:
        return ExperiencePreference(target_role=target_role or "공통")
    return ExperiencePreference.model_validate({key: row[key] for key in ExperiencePreference.model_fields})


def save_preference(experience_id: int, preference: ExperiencePreference, user_id: int = 1) -> None:
    with connect() as conn:
        _require_experience_owner(conn, experience_id, user_id)
        conn.execute(
            """INSERT INTO experience_preferences
               (experience_id, target_role, user_preference, do_not_use, preferred_focus, ownership_notes)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(experience_id, target_role) DO UPDATE SET
                 user_preference=excluded.user_preference,
                 do_not_use=excluded.do_not_use,
                 preferred_focus=excluded.preferred_focus,
                 ownership_notes=excluded.ownership_notes,
                 updated_at=CURRENT_TIMESTAMP""",
            (experience_id, *preference.model_dump().values()),
        )


def add_version(
    experience_id: int,
    profile: ExperienceData,
    change_note: str,
    created_by: str,
    correction_text: str = "",
    user_id: int = 1,
) -> int:
    with connect() as conn:
        _require_experience_owner(conn, experience_id, user_id)
        next_number = conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 FROM experience_versions WHERE experience_id=?",
            (experience_id,),
        ).fetchone()[0]
        version_id = _insert_id(
            conn,
            """INSERT INTO experience_versions
               (experience_id, version_number, profile_json, change_note, created_by)
               VALUES (?, ?, ?, ?, ?)""",
            (experience_id, next_number, profile.model_dump_json(), change_note.strip(), created_by),
        )
        conn.execute(
            """UPDATE experiences SET current_version_id=?, experience_name=?, review_status='User Editing',
               updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (version_id, profile.experience_name or "이름 미확인 경험", experience_id),
        )
        if correction_text.strip():
            conn.execute(
                "INSERT INTO experience_corrections(experience_id, correction_text) VALUES (?, ?)",
                (experience_id, correction_text.strip()),
            )
        return version_id


def approve_version(experience_id: int, version_id: int, user_id: int = 1) -> None:
    with connect() as conn:
        _require_experience_owner(conn, experience_id, user_id)
        version = conn.execute(
            "SELECT profile_json FROM experience_versions WHERE id=? AND experience_id=?",
            (version_id, experience_id),
        ).fetchone()
        if not version:
            raise ValueError("해당 경험의 버전이 아닙니다.")
        name = ExperienceData.model_validate_json(version["profile_json"]).experience_name or "이름 미확인 경험"
        conn.execute("UPDATE experience_versions SET is_approved=0 WHERE experience_id=?", (experience_id,))
        conn.execute("UPDATE experience_versions SET is_approved=1 WHERE id=?", (version_id,))
        conn.execute(
            """UPDATE experiences SET current_version_id=?, experience_name=?, review_status='Verified',
               updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (version_id, name, experience_id),
        )


def approve_all_experiences(user_id: int = 1) -> int:
    with connect() as conn:
        pending = conn.execute(
            "SELECT id, current_version_id FROM experiences WHERE user_id=? AND review_status<>'Verified'",
            (user_id,),
        ).fetchall()
        for row in pending:
            conn.execute("UPDATE experience_versions SET is_approved=0 WHERE experience_id=?", (row["id"],))
            conn.execute("UPDATE experience_versions SET is_approved=1 WHERE id=?", (row["current_version_id"],))
        conn.execute(
            """UPDATE experiences SET review_status='Verified', updated_at=CURRENT_TIMESTAMP
               WHERE user_id=? AND review_status<>'Verified'""",
            (user_id,),
        )
    return len(pending)


def log_ai_call(
    task: str,
    model: str,
    input_summary: str,
    output_json: str,
    token_usage: int | None,
    latency_ms: int,
    success: bool,
    error: str = "",
    user_id: int = 1,
) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO ai_call_logs
               (user_id, task, model, input_summary, output_json, token_usage, latency_ms, success, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, task, model, input_summary, output_json, token_usage, latency_ms, int(success), error),
        )


def save_job_description(analysis: JDAnalysis, raw_text: str, user_id: int = 1) -> int:
    with connect() as conn:
        jd_id = _insert_id(
            conn,
            """INSERT INTO job_descriptions(user_id, company, job_title, raw_text, analysis_json)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, analysis.company, analysis.job_title, raw_text, analysis.model_dump_json()),
        )
        _replace_job_skills(conn, jd_id, analysis)
        return jd_id


def update_job_description(jd_id: int, analysis: JDAnalysis, raw_text: str, user_id: int = 1) -> None:
    with connect() as conn:
        updated = conn.execute(
            """UPDATE job_descriptions SET company=?, job_title=?, raw_text=?, analysis_json=?
               WHERE id=? AND user_id=?""",
            (analysis.company, analysis.job_title, raw_text, analysis.model_dump_json(), jd_id, user_id),
        ).rowcount
        if not updated:
            raise ValueError("채용공고를 찾을 수 없습니다.")
        _replace_job_skills(conn, jd_id, analysis)


def delete_job_description(jd_id: int, user_id: int = 1) -> None:
    with connect() as conn:
        _require_jd_owner(conn, jd_id, user_id)
        conn.execute("DELETE FROM job_descriptions WHERE id=?", (jd_id,))


def _replace_job_skills(conn: sqlite3.Connection, jd_id: int, analysis: JDAnalysis) -> None:
    conn.execute("DELETE FROM job_skills WHERE job_description_id=?", (jd_id,))
    groups = {
        "required": analysis.required_skills,
        "preferred": analysis.preferred_skills,
        "technical": analysis.technical_skills,
        "domain": analysis.domain_knowledge,
        "behavioral": analysis.behavioral_skills,
        "tool": analysis.tools,
    }
    for skill_type, skills in groups.items():
        for skill in skills:
            if skill.name.strip():
                conn.execute(
                    """INSERT INTO job_skills
                       (job_description_id, skill_name, skill_type, importance, is_required)
                       VALUES (?, ?, ?, ?, ?)""",
                    (jd_id, skill.name.strip(), skill_type, skill.importance, int(skill_type == "required")),
                )


def list_job_descriptions(user_id: int = 1) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT jd.id, jd.company, jd.job_title, jd.application_status,
                      jd.deadline, jd.application_memo, jd.created_at,
                      COUNT(DISTINCT mr.id) AS match_count
               FROM job_descriptions jd
               LEFT JOIN experience_match_results mr ON mr.job_description_id=jd.id
               WHERE jd.user_id=?
               GROUP BY jd.id ORDER BY jd.id DESC""",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_job_description(jd_id: int, user_id: int = 1) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM job_descriptions WHERE id=? AND user_id=?", (jd_id, user_id)
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["analysis"] = json.loads(result.pop("analysis_json"))
    return result


def update_application_tracking(
    jd_id: int,
    status: str,
    deadline: str = "",
    memo: str = "",
    user_id: int = 1,
) -> None:
    if status not in APPLICATION_STATUSES:
        raise ValueError("지원 상태가 올바르지 않습니다.")
    deadline = deadline.strip()
    if deadline:
        try:
            date.fromisoformat(deadline)
        except ValueError as exc:
            raise ValueError("마감일은 YYYY-MM-DD 형식으로 입력해 주세요.") from exc
    with connect() as conn:
        _require_jd_owner(conn, jd_id, user_id)
        conn.execute(
            """UPDATE job_descriptions
               SET application_status=?, deadline=?, application_memo=?
               WHERE id=?""",
            (status, deadline, memo.strip(), jd_id),
        )


def list_application_folders(user_id: int = 1) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT jd.id, jd.company, jd.job_title, jd.application_status,
                      jd.deadline, jd.application_memo, jd.created_at,
                      COUNT(DISTINCT q.id) AS question_count,
                      COUNT(DISTINCT o.id) AS outline_count,
                      COUNT(DISTINCT d.id) AS draft_count,
                      MAX(d.created_at) AS latest_draft_at
               FROM job_descriptions jd
               LEFT JOIN essay_questions q ON q.job_description_id=jd.id
               LEFT JOIN essay_outlines o ON o.essay_question_id=q.id
               LEFT JOIN essay_drafts d ON d.essay_outline_id=o.id
               WHERE jd.user_id=?
               GROUP BY jd.id
               ORDER BY CASE WHEN jd.deadline='' THEN 1 ELSE 0 END, jd.deadline, jd.id DESC""",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_verified_experiences(user_id: int = 1) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT e.id, e.experience_name, e.current_version_id AS version_id, v.profile_json
               FROM experiences e JOIN experience_versions v ON v.id=e.current_version_id
               WHERE e.user_id=? AND e.review_status='Verified' ORDER BY e.id""",
            (user_id,),
        ).fetchall()
        results: list[dict] = []
        for row in rows:
            facts = conn.execute(
                "SELECT fact_text, evidence_text FROM source_facts WHERE experience_id=? ORDER BY id",
                (row["id"],),
            ).fetchall()
            preferences = conn.execute(
                """SELECT target_role, user_preference, do_not_use, preferred_focus, ownership_notes
                   FROM experience_preferences WHERE experience_id=?""",
                (row["id"],),
            ).fetchall()
            results.append(
                dict(row)
                | {
                    "profile": json.loads(row["profile_json"]),
                    "facts": [dict(item) for item in facts],
                    "preferences": [dict(item) for item in preferences],
                }
            )
    return results


def save_match_results(jd_id: int, matches: list[dict], user_id: int = 1) -> None:
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM job_descriptions WHERE id=? AND user_id=?", (jd_id, user_id)).fetchone():
            raise ValueError("이 프로필의 채용공고가 아닙니다.")
        conn.execute(
            "DELETE FROM experience_match_results WHERE job_description_id=? AND essay_question_id IS NULL",
            (jd_id,),
        )
        for match in matches:
            _require_experience_owner(conn, match["experience_id"], user_id)
            explanation = match["explanation"] | {
                "matching_skills": match.get("matching_skills", []),
                "profile_matching_skills": match.get("profile_matching_skills", []),
                "missing_skills": match.get("missing_skills", []),
                "preferred_focus": match.get("preferred_focus", ""),
            }
            conn.execute(
                """INSERT INTO experience_match_results
                   (job_description_id, experience_id, rank, score, breakdown_json, explanation_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    jd_id,
                    match["experience_id"],
                    match["rank"],
                    match["score"],
                    json.dumps(match["breakdown"], ensure_ascii=False),
                    json.dumps(explanation, ensure_ascii=False),
                ),
            )


def get_match_results(jd_id: int, user_id: int = 1) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT mr.*, e.experience_name
               FROM experience_match_results mr
               JOIN experiences e ON e.id=mr.experience_id
               JOIN job_descriptions jd ON jd.id=mr.job_description_id
               WHERE mr.job_description_id=? AND mr.essay_question_id IS NULL
                 AND e.user_id=? AND jd.user_id=? ORDER BY mr.rank""",
            (jd_id, user_id, user_id),
        ).fetchall()
    results: list[dict] = []
    for row in rows:
        explanation = json.loads(row["explanation_json"])
        results.append(
            dict(row)
            | {
                "breakdown": json.loads(row["breakdown_json"]),
                "matching_skills": explanation.pop("matching_skills", []),
                "profile_matching_skills": explanation.pop("profile_matching_skills", []),
                "missing_skills": explanation.pop("missing_skills", []),
                "preferred_focus": explanation.pop("preferred_focus", ""),
                "explanation": explanation,
            }
        )
    return results


def get_cached_embedding(
    entity_type: str, entity_id: int, model: str, content_hash: str, user_id: int = 1
) -> list[float] | None:
    with connect() as conn:
        row = conn.execute(
            """SELECT vector_json FROM embeddings
               WHERE entity_type=? AND entity_id=? AND model=? AND content_hash=? AND user_id=?""",
            (entity_type, entity_id, model, content_hash, user_id),
        ).fetchone()
    return json.loads(row["vector_json"]) if row else None


def save_embedding(
    entity_type: str, entity_id: int, model: str, content_hash: str, vector: list[float], user_id: int = 1
) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO embeddings
               (user_id, entity_type, entity_id, model, content_hash, vector_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, entity_type, entity_id, model, content_hash, json.dumps(vector)),
        )


def _require_experience_owner(conn: sqlite3.Connection, experience_id: int, user_id: int) -> None:
    if not conn.execute("SELECT 1 FROM experiences WHERE id=? AND user_id=?", (experience_id, user_id)).fetchone():
        raise ValueError("이 프로필의 경험이 아닙니다.")


def save_essay_question(
    jd_id: int,
    question: str,
    character_limit: int | None,
    optional_note: str,
    analysis: QuestionAnalysis,
    user_id: int = 1,
) -> int:
    if not question.strip():
        raise ValueError("자기소개서 문항을 입력해 주세요.")
    with connect() as conn:
        _require_jd_owner(conn, jd_id, user_id)
        return _insert_id(
            conn,
            """INSERT INTO essay_questions
               (job_description_id, question, character_limit, optional_note, analysis_json)
               VALUES (?, ?, ?, ?, ?)""",
            (jd_id, question.strip(), character_limit, optional_note.strip(), analysis.model_dump_json()),
        )


def update_essay_question(
    question_id: int,
    question: str,
    character_limit: int | None,
    optional_note: str,
    analysis: QuestionAnalysis,
    user_id: int = 1,
) -> None:
    if not question.strip():
        raise ValueError("자기소개서 문항을 입력해 주세요.")
    with connect() as conn:
        _require_question_owner(conn, question_id, user_id)
        conn.execute(
            """UPDATE essay_questions
               SET question=?, character_limit=?, optional_note=?, analysis_json=? WHERE id=?""",
            (question.strip(), character_limit, optional_note.strip(), analysis.model_dump_json(), question_id),
        )


def list_essay_questions(jd_id: int, user_id: int = 1) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT q.id, q.question, q.character_limit, q.optional_note, q.analysis_json
               FROM essay_questions q JOIN job_descriptions jd ON jd.id=q.job_description_id
               WHERE q.job_description_id=? AND jd.user_id=? ORDER BY q.id""",
            (jd_id, user_id),
        ).fetchall()
    return [dict(row) | {"analysis": json.loads(row["analysis_json"])} for row in rows]


def get_essay_question(question_id: int, user_id: int = 1) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            """SELECT q.* FROM essay_questions q
               JOIN job_descriptions jd ON jd.id=q.job_description_id
               WHERE q.id=? AND jd.user_id=?""",
            (question_id, user_id),
        ).fetchone()
    return dict(row) | {"analysis": json.loads(row["analysis_json"])} if row else None


def delete_essay_question(question_id: int, user_id: int = 1) -> None:
    with connect() as conn:
        _require_question_owner(conn, question_id, user_id)
        conn.execute("DELETE FROM essay_questions WHERE id=?", (question_id,))


def save_question_match_results(
    jd_id: int, question_id: int, matches: list[dict], user_id: int = 1
) -> None:
    with connect() as conn:
        _require_jd_owner(conn, jd_id, user_id)
        question = _require_question_owner(conn, question_id, user_id)
        if question["job_description_id"] != jd_id:
            raise ValueError("선택한 JD의 문항이 아닙니다.")
        conn.execute(
            "DELETE FROM experience_match_results WHERE job_description_id=? AND essay_question_id=?",
            (jd_id, question_id),
        )
        for match in matches:
            _require_experience_owner(conn, match["experience_id"], user_id)
            details = {key: value for key, value in match.items() if key not in {"experience_id", "rank", "score", "breakdown"}}
            conn.execute(
                """INSERT INTO experience_match_results
                   (job_description_id, essay_question_id, experience_id, rank, score, breakdown_json, explanation_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    jd_id,
                    question_id,
                    match["experience_id"],
                    match["rank"],
                    match["score"],
                    json.dumps(match["breakdown"], ensure_ascii=False),
                    json.dumps(details, ensure_ascii=False),
                ),
            )


def get_question_match_results(question_id: int, user_id: int = 1) -> list[dict]:
    with connect() as conn:
        _require_question_owner(conn, question_id, user_id)
        rows = conn.execute(
            """SELECT mr.*, e.experience_name
               FROM experience_match_results mr JOIN experiences e ON e.id=mr.experience_id
               WHERE mr.essay_question_id=? AND e.user_id=? ORDER BY mr.rank""",
            (question_id, user_id),
        ).fetchall()
    return [
        dict(row)
        | json.loads(row["explanation_json"])
        | {"breakdown": json.loads(row["breakdown_json"])}
        for row in rows
    ]


def save_recommendation_ground_truth(
    jd_id: int, ranked_experience_ids: list[int], user_id: int = 1
) -> None:
    ids = [experience_id for experience_id in ranked_experience_ids if experience_id]
    if not ids or len(ids) > 3 or len(ids) != len(set(ids)):
        raise ValueError("서로 다른 경험을 1~3개 순서대로 선택해 주세요.")
    with connect() as conn:
        _require_jd_owner(conn, jd_id, user_id)
        for experience_id in ids:
            _require_experience_owner(conn, experience_id, user_id)
        conn.execute("DELETE FROM recommendation_ground_truth WHERE job_description_id=?", (jd_id,))
        conn.executemany(
            """INSERT INTO recommendation_ground_truth(job_description_id, experience_id, rank)
               VALUES (?, ?, ?)""",
            [(jd_id, experience_id, rank) for rank, experience_id in enumerate(ids, 1)],
        )


def get_recommendation_ground_truth(jd_id: int, user_id: int = 1) -> list[dict]:
    with connect() as conn:
        _require_jd_owner(conn, jd_id, user_id)
        rows = conn.execute(
            """SELECT gt.*, e.experience_name FROM recommendation_ground_truth gt
               JOIN experiences e ON e.id=gt.experience_id
               WHERE gt.job_description_id=? AND e.user_id=? ORDER BY gt.rank""",
            (jd_id, user_id),
        ).fetchall()
    return [dict(row) for row in rows]


def list_evaluated_jd_ids(user_id: int = 1) -> list[int]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT DISTINCT gt.job_description_id FROM recommendation_ground_truth gt
               JOIN job_descriptions jd ON jd.id=gt.job_description_id
               WHERE jd.user_id=? ORDER BY gt.job_description_id""",
            (user_id,),
        ).fetchall()
    return [row[0] for row in rows]


def save_essay_outline(
    question_id: int,
    experience_id: int | None,
    outline: EssayOutline,
    user_id: int = 1,
) -> int:
    with connect() as conn:
        _require_question_owner(conn, question_id, user_id)
        experience_ids = list(dict.fromkeys([item for item in [experience_id, *outline.experience_ids] if item]))
        material_ids = list(dict.fromkeys(outline.material_ids))
        if not experience_ids and not material_ids:
            raise ValueError("개요에 사용할 경험 또는 개인 소재를 선택해 주세요.")
        if len(experience_ids) + len(material_ids) > 3:
            raise ValueError("개요에는 경험과 개인 소재를 합해 최대 3개까지 사용할 수 있습니다.")
        for selected_id in experience_ids:
            _require_experience_owner(conn, selected_id, user_id)
            if not conn.execute(
                "SELECT 1 FROM experiences WHERE id=? AND review_status='Verified'", (selected_id,)
            ).fetchone():
                raise ValueError("Verified 상태인 경험만 개요에 사용할 수 있습니다.")
        for selected_id in material_ids:
            _require_personal_material_owner(conn, selected_id, user_id)
        outline = outline.model_copy(update={"experience_ids": experience_ids, "material_ids": material_ids})
        version = conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 FROM essay_outlines WHERE essay_question_id=?",
            (question_id,),
        ).fetchone()[0]
        return _insert_id(
            conn,
            """INSERT INTO essay_outlines
               (essay_question_id, experience_id, version_number, outline_json)
               VALUES (?, ?, ?, ?)""",
            (question_id, experience_id, version, outline.model_dump_json()),
        )


def list_essay_outlines(question_id: int, user_id: int = 1) -> list[dict]:
    with connect() as conn:
        _require_question_owner(conn, question_id, user_id)
        rows = conn.execute(
            """SELECT o.*, e.experience_name FROM essay_outlines o
               JOIN essay_questions q ON q.id=o.essay_question_id
               JOIN job_descriptions jd ON jd.id=q.job_description_id
               LEFT JOIN experiences e ON e.id=o.experience_id
               WHERE o.essay_question_id=? AND jd.user_id=? ORDER BY o.version_number DESC""",
            (question_id, user_id),
        ).fetchall()
    materials = {item["id"]: item for item in list_personal_materials(user_id)}
    results = []
    for row in rows:
        outline = json.loads(row["outline_json"])
        material = materials.get(next(iter(outline.get("material_ids", [])), 0))
        results.append(dict(row) | {
            "outline": outline,
            "experience_name": row["experience_name"] or (material["title"] if material else "개인 소재"),
        })
    return results


def approve_essay_outline(outline_id: int, user_id: int = 1) -> None:
    with connect() as conn:
        row = conn.execute(
            """SELECT o.essay_question_id FROM essay_outlines o
               JOIN essay_questions q ON q.id=o.essay_question_id
               JOIN job_descriptions jd ON jd.id=q.job_description_id
               WHERE o.id=? AND jd.user_id=?""",
            (outline_id, user_id),
        ).fetchone()
        if not row:
            raise ValueError("이 프로필의 개요가 아닙니다.")
        conn.execute("UPDATE essay_outlines SET is_approved=0 WHERE essay_question_id=?", (row["essay_question_id"],))
        conn.execute("UPDATE essay_outlines SET is_approved=1 WHERE id=?", (outline_id,))


def list_approved_outlines(user_id: int = 1) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT o.id, o.experience_id, o.version_number, o.outline_json, o.created_at,
                      q.id AS question_id, q.question, q.character_limit,
                      jd.id AS job_description_id, jd.company, jd.job_title, e.experience_name
               FROM essay_outlines o
               JOIN essay_questions q ON q.id=o.essay_question_id
               JOIN job_descriptions jd ON jd.id=q.job_description_id
               LEFT JOIN experiences e ON e.id=o.experience_id
               WHERE o.is_approved=1 AND jd.user_id=?
               ORDER BY o.id DESC""",
            (user_id,),
        ).fetchall()
    materials = {item["id"]: item for item in list_personal_materials(user_id)}
    results = []
    for row in rows:
        outline = json.loads(row["outline_json"])
        material = materials.get(next(iter(outline.get("material_ids", [])), 0))
        results.append(dict(row) | {
            "outline": outline,
            "experience_name": row["experience_name"] or (material["title"] if material else "개인 소재"),
        })
    return results


def get_outline_context(outline_id: int, user_id: int = 1) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            """SELECT o.*, q.question, q.character_limit, q.optional_note, q.analysis_json,
                      jd.id AS job_description_id, jd.company, jd.job_title, jd.analysis_json AS jd_analysis_json
               FROM essay_outlines o
               JOIN essay_questions q ON q.id=o.essay_question_id
               JOIN job_descriptions jd ON jd.id=q.job_description_id
               WHERE o.id=? AND jd.user_id=?""",
            (outline_id, user_id),
        ).fetchone()
    if not row:
        return None
    outline = json.loads(row["outline_json"])
    experience_ids = outline.get("experience_ids") or [row["experience_id"]]
    experiences = [item for item in (get_experience(item_id, user_id) for item_id in experience_ids if item_id) if item]
    materials = [
        item
        for item in (get_personal_material(item_id, user_id) for item_id in outline.get("material_ids", []))
        if item
    ]
    if not experiences and not materials:
        return None
    return {
        "id": row["id"],
        "is_approved": bool(row["is_approved"]),
        "outline": outline,
        "question": {
            "id": row["essay_question_id"],
            "question": row["question"],
            "character_limit": row["character_limit"],
            "optional_note": row["optional_note"],
            "analysis": json.loads(row["analysis_json"]),
        },
        "jd": {
            "id": row["job_description_id"],
            "company": row["company"],
            "job_title": row["job_title"],
            "analysis": json.loads(row["jd_analysis_json"]),
        },
        "profile": get_profile(user_id).model_dump(),
        "experience": experiences[0] if experiences else None,
        "experiences": experiences,
        "materials": materials,
    }


def delete_essay_outline(outline_id: int, user_id: int = 1) -> None:
    with connect() as conn:
        _require_outline_owner(conn, outline_id, user_id)
        conn.execute("DELETE FROM essay_outlines WHERE id=?", (outline_id,))


def save_essay_draft(outline_id: int, content: str, user_id: int = 1) -> int:
    content = content.strip()
    if not content:
        raise ValueError("초안 내용을 입력해 주세요.")
    with connect() as conn:
        outline = _require_outline_owner(conn, outline_id, user_id, approved_only=True)
        if outline["character_limit"] and len(content) > outline["character_limit"]:
            raise ValueError(
                f"초안이 글자 제한을 {len(content) - outline['character_limit']}자 초과했습니다."
            )
        return _insert_id(
            conn,
            "INSERT INTO essay_drafts(essay_outline_id, content) VALUES (?, ?)",
            (outline_id, content),
        )


def list_essay_drafts(outline_id: int, user_id: int = 1) -> list[dict]:
    with connect() as conn:
        _require_outline_owner(conn, outline_id, user_id)
        rows = conn.execute(
            "SELECT * FROM essay_drafts WHERE essay_outline_id=? ORDER BY id DESC", (outline_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def delete_essay_draft(draft_id: int, user_id: int = 1) -> None:
    with connect() as conn:
        owned = conn.execute(
            """SELECT 1 FROM essay_drafts d
               JOIN essay_outlines o ON o.id=d.essay_outline_id
               JOIN essay_questions q ON q.id=o.essay_question_id
               JOIN job_descriptions jd ON jd.id=q.job_description_id
               WHERE d.id=? AND jd.user_id=?""",
            (draft_id, user_id),
        ).fetchone()
        if not owned:
            raise ValueError("이 프로필의 Draft가 아닙니다.")
        conn.execute("DELETE FROM essay_drafts WHERE id=?", (draft_id,))


def save_fact_check_results(
    outline_id: int,
    draft_id: int,
    results: list[FactCheckItem],
    user_id: int = 1,
) -> None:
    with connect() as conn:
        _require_outline_owner(conn, outline_id, user_id)
        if not conn.execute(
            "SELECT 1 FROM essay_drafts WHERE id=? AND essay_outline_id=?", (draft_id, outline_id)
        ).fetchone():
            raise ValueError("선택한 개요의 초안이 아닙니다.")
        conn.execute("DELETE FROM fact_check_results WHERE essay_draft_id=?", (draft_id,))
        conn.executemany(
            """INSERT INTO fact_check_results
               (essay_outline_id, essay_draft_id, sentence, status, evidence_json)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    outline_id,
                    draft_id,
                    item.sentence,
                    item.status,
                    json.dumps({"evidence": item.evidence, "reason": item.reason}, ensure_ascii=False),
                )
                for item in results
            ],
        )


def get_fact_check_results(draft_id: int, user_id: int = 1) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT f.* FROM fact_check_results f
               JOIN essay_drafts d ON d.id=f.essay_draft_id
               JOIN essay_outlines o ON o.id=d.essay_outline_id
               JOIN essay_questions q ON q.id=o.essay_question_id
               JOIN job_descriptions jd ON jd.id=q.job_description_id
               WHERE f.essay_draft_id=? AND jd.user_id=? ORDER BY f.id""",
            (draft_id, user_id),
        ).fetchall()
    results = []
    for row in rows:
        details = json.loads(row["evidence_json"])
        if isinstance(details, list):
            details = {"evidence": details, "reason": ""}
        results.append(dict(row) | details)
    return results


def count_experience_uses(jd_id: int, experience_id: int, user_id: int = 1) -> int:
    with connect() as conn:
        _require_jd_owner(conn, jd_id, user_id)
        _require_experience_owner(conn, experience_id, user_id)
        return conn.execute(
            """SELECT COUNT(DISTINCT q.id) FROM essay_outlines o
               JOIN essay_questions q ON q.id=o.essay_question_id
               WHERE q.job_description_id=? AND o.experience_id=? AND o.is_approved=1""",
            (jd_id, experience_id),
        ).fetchone()[0]


def get_dashboard_metrics(user_id: int = 1) -> dict:
    with connect() as conn:
        row = conn.execute(
            """SELECT
                 (SELECT COUNT(*) FROM experiences WHERE user_id=?) AS experiences,
                 (SELECT COUNT(*) FROM experiences WHERE user_id=? AND review_status='Verified') AS verified,
                 (SELECT COUNT(*) FROM job_descriptions WHERE user_id=?) AS jobs,
                 (SELECT COUNT(*) FROM essay_outlines o JOIN essay_questions q ON q.id=o.essay_question_id
                    JOIN job_descriptions jd ON jd.id=q.job_description_id
                    WHERE jd.user_id=? AND o.is_approved=1) AS approved_outlines,
                 (SELECT COUNT(*) FROM essay_drafts d JOIN essay_outlines o ON o.id=d.essay_outline_id
                    JOIN essay_questions q ON q.id=o.essay_question_id
                    JOIN job_descriptions jd ON jd.id=q.job_description_id WHERE jd.user_id=?) AS drafts""",
            (user_id, user_id, user_id, user_id, user_id),
        ).fetchone()
    return dict(row)


def list_jd_skill_frequencies(user_id: int = 1) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT js.skill_name, GROUP_CONCAT(DISTINCT js.skill_type) AS skill_types,
                      COUNT(DISTINCT jd.id) AS job_count,
                      ROUND(AVG(js.importance), 2) AS average_importance
               FROM job_skills js JOIN job_descriptions jd ON jd.id=js.job_description_id
               WHERE jd.user_id=? GROUP BY lower(js.skill_name)
               ORDER BY job_count DESC, average_importance DESC, js.skill_name LIMIT 30""",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _require_jd_owner(conn: sqlite3.Connection, jd_id: int, user_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM job_descriptions WHERE id=? AND user_id=?", (jd_id, user_id)).fetchone()
    if not row:
        raise ValueError("이 프로필의 채용공고가 아닙니다.")
    return row


def _require_personal_material_owner(
    conn: sqlite3.Connection, material_id: int, user_id: int
) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM personal_materials WHERE id=? AND user_id=?", (material_id, user_id)
    ).fetchone()
    if not row:
        raise ValueError("현재 프로필의 개인 소재가 아닙니다.")
    return row


def _require_outline_owner(
    conn: sqlite3.Connection,
    outline_id: int,
    user_id: int,
    approved_only: bool = False,
) -> sqlite3.Row:
    row = conn.execute(
        """SELECT o.*, q.character_limit FROM essay_outlines o
           JOIN essay_questions q ON q.id=o.essay_question_id
           JOIN job_descriptions jd ON jd.id=q.job_description_id
           WHERE o.id=? AND jd.user_id=?""",
        (outline_id, user_id),
    ).fetchone()
    if not row:
        raise ValueError("이 프로필의 개요가 아닙니다.")
    if approved_only and not row["is_approved"]:
        raise ValueError("승인된 개요에서만 초안을 만들 수 있습니다.")
    return row


def _require_question_owner(conn: sqlite3.Connection, question_id: int, user_id: int) -> sqlite3.Row:
    row = conn.execute(
        """SELECT q.* FROM essay_questions q JOIN job_descriptions jd ON jd.id=q.job_description_id
           WHERE q.id=? AND jd.user_id=?""",
        (question_id, user_id),
    ).fetchone()
    if not row:
        raise ValueError("이 프로필의 자기소개서 문항이 아닙니다.")
    return row
