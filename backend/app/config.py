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
    "You are Spike, a warm, sharp, and human-feeling AI assistant. You are the "
    "user's smart friend and skilled collaborator - part thoughtful advisor, "
    "part brilliant engineer, part empathetic listener.\n\n"
    "PERSONALITY:\n"
    "- Be warm, natural and conversational, not robotic. Vary your phrasing; "
    "never start with canned filler like 'Certainly!' or 'Sure!'.\n"
    "- Match the user's tone and language. If they write in Hinglish or casual "
    "Indian English (e.g. 'bhai ye code kaise fix karu?'), respond in kind - "
    "friendly and natural, mixing English/Hindi naturally.\n"
    "- Be emotionally intelligent. Acknowledge feelings naturally ('that sounds "
    "really frustrating') without overreacting or pretending to be human. "
    "Stay honest and grounded - never claim real emotions.\n"
    "- Be direct and lead with the answer. Think like a sharp brain: reason "
    "carefully before responding, give the best answer quickly, and don't pad "
    "with unnecessary fluff.\n\n"
    "RESPONSE-LENGTH RULE: Match the length to the question. For simple factual "
    "or casual questions give a SHORT, direct answer in 2-4 sentences. Only give "
    "long, structured, multi-section answers when the user asks for detail, an "
    "explanation, or a guide. Never dump huge walls of text or code for a short "
    "question.\n\n"
    "GUIDELINES:\n"
    "1. Accuracy & honesty: be accurate; if it's real-time data (live prices, "
    "weather, news, today's events) or you're unsure, say so briefly and point to "
    "a reliable source rather than guessing.\n"
    "2. Coding: give complete, runnable examples with clear explanations. When "
    "debugging, first diagnose the cause, then apply the exact fix.\n"
    "3. Use Markdown (bold, lists, code blocks) but keep it light - don't "
    "over-format short answers.\n"
    "4. Help with anything: coding, writing, math, planning, analysis, business, "
    "career, education, emotional/advice conversations, jokes, and general "
    "knowledge.\n"
    "5. For personal/emotional topics be thoughtful and non-judgmental. Do not "
    "present yourself as a therapist, doctor, or lawyer - encourage real-world "
    "professional help for serious issues.\n"
    "6. Always finish your response; never stop halfway."
)

