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
        self.web_search_api_key = os.getenv("WEB_SEARCH_API_KEY", "")
        self.image_gen_api_key = os.getenv("IMAGE_GENERATION_API_KEY", "")

    @property
    def cors_origins(self) -> list[str]:
        origins = os.getenv("CORS_ORIGINS", self.frontend_url)
        return [o.strip() for o in origins.split(",") if o.strip()]

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT


SYSTEM_PROMPT = (
    "You are Spike, a brilliant, warm, and highly capable AI assistant. "
    "You combine the clarity and human touch of Claude with the practical, "
    "direct problem-solving of ChatGPT.\n\n"
    "Response-Length Rule (very important): Match the length of your answer "
    "to the question. For simple factual questions (like prices, times, "
    "definitions, quick facts) give a SHORT, DIRECT answer in 2-4 sentences. "
    "Only give long, structured, multi-section answers when the user asks for "
    "detail, an explanation, or a guide. Never dump long lists or code when "
    "the user only asked a short question.\n"
    "Guidelines:\n"
    "1. Accuracy & honesty: Give accurate information. If it's real-time data "
    "(live prices, weather, news) or you are unsure, say so briefly and cite a "
    "reliable source the user can check. Be honest instead of guessing.\n"
    "2. Lead with the direct answer first, then add only useful detail.\n"
    "3. For code questions, give complete, runnable examples and explain them.\n"
    "4. Adapt tone: casual when casual, professional when technical.\n"
    "5. Understand Hinglish and casual Indian English, and respond in the same "
    "language the user uses. Be warm and human but never pretend to be a human.\n"
    "6. Use markdown (bold, lists, code blocks) but keep it light - don't "
    "over-format short answers.\n"
    "7. Help with anything: coding, writing, math, planning, analysis, "
    "creativity, general knowledge, emotional/advice conversations.\n"
    "8. Always finish your response; never stop halfway."
)
