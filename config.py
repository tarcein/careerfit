import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DB_PATH = Path(os.getenv("CAREERFIT_DB_PATH", BASE_DIR / "data" / "careerfit.db"))
DATABASE_URL = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL", "")
UPLOAD_DIR = Path(os.getenv("CAREERFIT_UPLOAD_DIR", BASE_DIR / "data" / "uploads"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini-2026-03-17")
OPENAI_DRAFT_MODEL = os.getenv("OPENAI_DRAFT_MODEL", OPENAI_MODEL)
EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_AI_INPUT_CHARS = 80_000
SUPPORTED_EXTENSIONS = {".pdf", ".pptx", ".docx", ".txt", ".md"}
MATCH_WEIGHTS = {
    "semantic_similarity": 40,
    "required_skill_coverage": 25,
    "technical_skill_match": 15,
    "relevant_result": 10,
    "evidence_reliability": 10,
}
