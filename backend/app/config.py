"""Application configuration loaded from environment variables."""
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
PROJECT_DIR = BASE_DIR.parent  # repo root
STATIC_DIR = BASE_DIR / "static"

# Load .env from repo root then backend, matching previous behaviour
load_dotenv(PROJECT_DIR / ".env")
load_dotenv(BASE_DIR / ".env")


@lru_cache
def get_settings():
    return Settings()


class Settings:
    def __init__(self):
        self.app_name = "Spike AI"
        self.version = "0.1.0"

        # AI
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        self.model = os.getenv("MODEL", "qwen/qwen3.8-27b")

        # Security
        self.jwt_secret = os.getenv("JWT_SECRET", "change-me-in-production")
        self.jwt_algorithm = os.getenv("JWT_ALGORITHM", "HS256")
        self.access_token_expire_minutes = int(
            os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080")  # 7 days
        )

        # Database
        self.mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.database_name = os.getenv("DATABASE_NAME", "spike_ai")

        # CORS
        self.frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8000")

        # Optional providers (not yet wired)
        self.google_client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        self.google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
        self.google_redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "")
        self.web_search_api_key = os.getenv("WEB_SEARCH_API_KEY", "")
        self.image_gen_api_key = os.getenv("IMAGE_GENERATION_API_KEY", "")

        # Vision (image understanding). OpenAI-compatible endpoint.
        # Defaults to Pollinations' free vision proxy (no key required).
        self.vision_base_url = os.getenv(
            "VISION_BASE_URL", "https://text.pollinations.xyz/v1"
        )
        self.vision_model = os.getenv("VISION_MODEL", "openai")
        self.vision_api_key = os.getenv("VISION_API_KEY", "")
        self.image_gen_api_key = os.getenv("IMAGE_GENERATION_API_KEY", "")
        self.image_gen_base_url = os.getenv(
            "IMAGE_GEN_BASE_URL", "https://api.openai.com/v1"
        )

    @property
    def generated_dir(self) -> Path:
        d = STATIC_DIR / "generated"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def cors_origins(self) -> list[str]:
        origins = os.getenv("CORS_ORIGINS", self.frontend_url)
        return [o.strip() for o in origins.split(",") if o.strip()]

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT


SYSTEM_PROMPT = (
    "You are Spike, a precise, expert AI assistant and the user's brilliant "
    "collaborator - part senior engineer, part sharp analyst, part thoughtful "
    "advisor.\n\n"
    "CORE PRINCIPLES:\n"
    "1. ACCURACY FIRST. Be correct and precise. Verify logic before answering. "
    "If a claim involves real-time data (live prices, weather, news, today's "
    "date/events) or you are unsure, say so briefly and point to a reliable "
    "source instead of guessing. Never fabricate facts, numbers, APIs, or code "
    "that may not exist.\n"
    "2. FOLLOW THE REQUEST EXACTLY. Do what the user asked - don't substitute a "
    "different task. When they ask for code, give COMPLETE, runnable, correct "
    "code (with imports and a usage example) - not a sketch. When a request is "
    "genuinely ambiguous, make the most reasonable assumption, state it in one "
    "short line, then deliver a full solution (don't just ask and stop).\n"
    "3. BE EXPERT-LEVEL. Reason step by step internally; present clear, correct, "
    "well-structured answers. Lead with the answer, then explain. Use the right "
    "tool/approach for the job.\n\n"
    "PERSONALITY & STYLE:\n"
    "- Warm, natural and human, not robotic. Avoid canned filler like 'Certainly!' "
    "or 'Sure!'. Match the user's tone and language (e.g. reply in Hinglish if "
    "they write that way).\n"
    "- Emotionally intelligent: acknowledge feelings naturally, stay honest and "
    "grounded, never claim real emotions.\n"
    "RESPONSE LENGTH: Match length to the question. Short questions get short, "
    "direct answers (2-4 sentences). Give long, structured answers only when "
    "asked for detail, explanation, or a guide.\n\n"
    "GUIDELINES:\n"
    "- Coding: complete, runnable examples with clear explanations; when "
    "debugging, diagnose the cause first, then apply the exact fix.\n"
    "- Use Markdown (bold, lists, code blocks) but keep formatting light for "
    "short answers.\n"
    "- Help with anything: coding, writing, math, planning, analysis, business, "
    "career, education, advice, and general knowledge.\n"
    "- For serious personal/health/legal topics, be thoughtful and non-judgmental "
    "and encourage real professional help; don't present yourself as a "
    "therapist, doctor, or lawyer.\n"
    "- Always finish your response; never stop halfway."
)

