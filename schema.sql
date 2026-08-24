PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
    email TEXT UNIQUE,
    display_name TEXT NOT NULL DEFAULT '나',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    nickname TEXT NOT NULL DEFAULT '',
    target_role TEXT NOT NULL DEFAULT '',
    industries TEXT NOT NULL DEFAULT '',
    major TEXT NOT NULL DEFAULT '',
    education TEXT NOT NULL DEFAULT '',
    certifications TEXT NOT NULL DEFAULT '',
    languages TEXT NOT NULL DEFAULT '',
    technical_skills TEXT NOT NULL DEFAULT '',
    courses TEXT NOT NULL DEFAULT '',
    activities TEXT NOT NULL DEFAULT '',
    role_description TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS uploaded_files (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    extracted_text TEXT NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, content_hash)
);

CREATE TABLE IF NOT EXISTS experiences (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    experience_name TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'AI Extracted'
      CHECK(review_status IN ('AI Extracted', 'User Editing', 'Verified')),
    current_version_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(current_version_id) REFERENCES experience_versions(id)
);

CREATE TABLE IF NOT EXISTS experience_versions (
    id INTEGER PRIMARY KEY,
    experience_id INTEGER NOT NULL REFERENCES experiences(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    profile_json TEXT NOT NULL,
    change_note TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL CHECK(created_by IN ('AI', 'User')),
    is_approved INTEGER NOT NULL DEFAULT 0 CHECK(is_approved IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(experience_id, version_number)
);

CREATE TABLE IF NOT EXISTS source_facts (
    id INTEGER PRIMARY KEY,
    experience_id INTEGER NOT NULL REFERENCES experiences(id) ON DELETE CASCADE,
    uploaded_file_id INTEGER NOT NULL REFERENCES uploaded_files(id) ON DELETE RESTRICT,
    fact_text TEXT NOT NULL,
    evidence_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS experience_sources (
    experience_id INTEGER NOT NULL REFERENCES experiences(id) ON DELETE CASCADE,
    uploaded_file_id INTEGER NOT NULL REFERENCES uploaded_files(id) ON DELETE RESTRICT,
    PRIMARY KEY(experience_id, uploaded_file_id)
);

CREATE TABLE IF NOT EXISTS experience_corrections (
    id INTEGER PRIMARY KEY,
    experience_id INTEGER NOT NULL REFERENCES experiences(id) ON DELETE CASCADE,
    correction_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS experience_preferences (
    id INTEGER PRIMARY KEY,
    experience_id INTEGER NOT NULL REFERENCES experiences(id) ON DELETE CASCADE,
    target_role TEXT NOT NULL DEFAULT '공통',
    user_preference TEXT NOT NULL DEFAULT '',
    do_not_use TEXT NOT NULL DEFAULT '',
    preferred_focus TEXT NOT NULL DEFAULT '',
    ownership_notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(experience_id, target_role)
);

CREATE TABLE IF NOT EXISTS job_profiles (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    focus_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS personal_materials (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '',
    memorable_point TEXT NOT NULL DEFAULT '',
    insight TEXT NOT NULL DEFAULT '',
    changed_action TEXT NOT NULL DEFAULT '',
    keywords TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_descriptions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company TEXT NOT NULL,
    job_title TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    analysis_json TEXT NOT NULL DEFAULT '{}',
    application_status TEXT NOT NULL DEFAULT '관심',
    deadline TEXT NOT NULL DEFAULT '',
    application_memo TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_skills (
    id INTEGER PRIMARY KEY,
    job_description_id INTEGER NOT NULL REFERENCES job_descriptions(id) ON DELETE CASCADE,
    skill_name TEXT NOT NULL,
    skill_type TEXT NOT NULL,
    importance REAL NOT NULL CHECK(importance BETWEEN 0 AND 1),
    is_required INTEGER NOT NULL DEFAULT 0 CHECK(is_required IN (0, 1))
);

CREATE TABLE IF NOT EXISTS essay_questions (
    id INTEGER PRIMARY KEY,
    job_description_id INTEGER NOT NULL REFERENCES job_descriptions(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    character_limit INTEGER,
    optional_note TEXT NOT NULL DEFAULT '',
    analysis_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS experience_match_results (
    id INTEGER PRIMARY KEY,
    job_description_id INTEGER NOT NULL REFERENCES job_descriptions(id) ON DELETE CASCADE,
    essay_question_id INTEGER REFERENCES essay_questions(id) ON DELETE CASCADE,
    experience_id INTEGER NOT NULL REFERENCES experiences(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    score REAL NOT NULL,
    breakdown_json TEXT NOT NULL,
    explanation_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recommendation_ground_truth (
    id INTEGER PRIMARY KEY,
    job_description_id INTEGER NOT NULL REFERENCES job_descriptions(id) ON DELETE CASCADE,
    experience_id INTEGER NOT NULL REFERENCES experiences(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL CHECK(rank BETWEEN 1 AND 3),
    UNIQUE(job_description_id, rank),
    UNIQUE(job_description_id, experience_id)
);

CREATE TABLE IF NOT EXISTS essay_outlines (
    id INTEGER PRIMARY KEY,
    essay_question_id INTEGER NOT NULL REFERENCES essay_questions(id) ON DELETE CASCADE,
    experience_id INTEGER REFERENCES experiences(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    outline_json TEXT NOT NULL,
    is_approved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS essay_drafts (
    id INTEGER PRIMARY KEY,
    essay_outline_id INTEGER NOT NULL REFERENCES essay_outlines(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fact_check_results (
    id INTEGER PRIMARY KEY,
    essay_outline_id INTEGER REFERENCES essay_outlines(id) ON DELETE CASCADE,
    essay_draft_id INTEGER REFERENCES essay_drafts(id) ON DELETE CASCADE,
    sentence TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('Verified', 'Needs Review', 'Unsupported')),
    evidence_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS ai_call_logs (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    task TEXT NOT NULL,
    model TEXT NOT NULL,
    input_summary TEXT NOT NULL,
    output_json TEXT NOT NULL DEFAULT '',
    token_usage INTEGER,
    latency_ms INTEGER NOT NULL,
    success INTEGER NOT NULL CHECK(success IN (0, 1)),
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('job_description', 'experience_version')),
    entity_id INTEGER NOT NULL,
    model TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, entity_type, entity_id, model, content_hash)
);

CREATE TRIGGER IF NOT EXISTS source_facts_no_update
BEFORE UPDATE ON source_facts
BEGIN
    SELECT RAISE(ABORT, 'source_facts are immutable');
END;

DROP TRIGGER IF EXISTS source_facts_no_delete;

CREATE TRIGGER source_facts_no_delete
BEFORE DELETE ON source_facts
WHEN EXISTS (SELECT 1 FROM experiences WHERE id=OLD.experience_id)
BEGIN
    SELECT RAISE(ABORT, 'source_facts are immutable');
END;

CREATE INDEX IF NOT EXISTS idx_experiences_user_status ON experiences(user_id, review_status);
CREATE INDEX IF NOT EXISTS idx_personal_materials_user ON personal_materials(user_id, category);
CREATE INDEX IF NOT EXISTS idx_versions_experience ON experience_versions(experience_id, version_number DESC);
CREATE INDEX IF NOT EXISTS idx_job_skills_jd ON job_skills(job_description_id);
CREATE INDEX IF NOT EXISTS idx_match_results_jd ON experience_match_results(job_description_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_embeddings_lookup ON embeddings(entity_type, entity_id, model, content_hash);
CREATE INDEX IF NOT EXISTS idx_essay_questions_jd ON essay_questions(job_description_id);
CREATE INDEX IF NOT EXISTS idx_essay_outlines_question ON essay_outlines(essay_question_id, version_number DESC);
CREATE INDEX IF NOT EXISTS idx_essay_drafts_outline ON essay_drafts(essay_outline_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_fact_checks_draft ON fact_check_results(essay_draft_id);
CREATE INDEX IF NOT EXISTS idx_recommendation_ground_truth_jd ON recommendation_ground_truth(job_description_id, rank);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_account ON auth_sessions(account_id, expires_at);
