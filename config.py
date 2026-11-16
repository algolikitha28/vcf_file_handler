
import os
from pathlib import Path
from dotenv import load_dotenv

# Project directory
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from .env
load_dotenv(BASE_DIR / ".env")


class Config:

    # Flask security
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY")

    # Database configuration
    SQLALCHEMY_DATABASE_URI = (
        f"sqlite:///{(BASE_DIR / 'users.db').as_posix()}"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload configuration
    UPLOAD_FOLDER = str(BASE_DIR / "uploads")

    MAX_CONTENT_LENGTH = 101 * 1024 * 1024

    ALLOWED_EXTENSIONS = {".vcf"}

    # Session security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv(
        "SESSION_COOKIE_SECURE", "False"
    ).lower() == "true"

    # Authentication settings
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
