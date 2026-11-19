import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    mode: str = "demo"
    sqlite_path: Path = ROOT / ".local" / "demo.sqlite3"
    openai_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    max_output_tokens: int = 1000
    firebase_json: str = ""
    firebase_path: str = ""
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:8000", "http://localhost:8000")

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env", override=False)
        cfg = cls(
            mode=os.getenv("APP_MODE", "demo"),
            openai_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            max_output_tokens=int(os.getenv("MAX_OUTPUT_TOKENS", "1000")),
            firebase_json=os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", ""),
            firebase_path=os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", ""),
            allowed_origins=tuple(x.strip().rstrip("/") for x in os.getenv(
                "ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000"
            ).split(",") if x.strip()),
        )
        if cfg.mode not in {"demo", "local", "production"}:
            raise ValueError("APP_MODE must be demo, local, or production")
        if not 128 <= cfg.max_output_tokens <= 2000:
            raise ValueError("MAX_OUTPUT_TOKENS must be between 128 and 2000")
        if cfg.mode == "local" and not cfg.openai_key:
            raise ValueError("Local GPT mode requires OPENAI_API_KEY; use APP_MODE=demo for an offline preview")
        if cfg.mode == "production":
            if not cfg.openai_key or not (cfg.firebase_json or cfg.firebase_path):
                raise ValueError("Production requires OpenAI and Firebase credentials; no demo fallback")
            if not cfg.allowed_origins or "*" in cfg.allowed_origins:
                raise ValueError("Production requires explicit ALLOWED_ORIGINS")
        return cfg
