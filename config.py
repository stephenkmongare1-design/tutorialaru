import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'tutorai.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
    MAX_CONTENT_LENGTH = 60 * 1024 * 1024  # 60 MB max upload

    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

    # Business rules / pricing (KES)
    TIER_PRICES = {
        "standard": int(os.environ.get("PRICE_STANDARD", 1200)),
        "national": int(os.environ.get("PRICE_NATIONAL", 3000)),
        "international": int(os.environ.get("PRICE_INTERNATIONAL", 6000)),
    }
    TIER_LABELS = {
        "standard": "Standard Teacher",
        "national": "National Teacher",
        "international": "International Teacher",
    }
    TEACHER_LICENSE_FEE = int(os.environ.get("TEACHER_LICENSE_FEE", 1500))
    TEACHER_LICENSE_YEARS = int(os.environ.get("TEACHER_LICENSE_YEARS", 3))

    CATEGORIES = {
        "pre_primary": "Pre-Primary (PP1 - PP2)",
        "primary": "Primary School (Grade 1 - 6)",
        "junior_school": "Junior School (Grade 7 - 9)",
        "senior_school": "Senior School / High School (Grade 10 - 12)",
    }

    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@tutorai.local")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@12345")

    ALLOWED_DOC_EXT = {"pdf", "png", "jpg", "jpeg", "webp"}
    ALLOWED_VIDEO_EXT = {"mp4", "webm", "mov", "mkv"}
    ALLOWED_BOOK_EXT = {"pdf", "epub"}
