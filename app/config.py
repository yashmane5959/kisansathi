import os
import socket
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Ensure socket resolution prefers IPv4 (AF_INET) to prevent IPv6 unreachable network errors
def _setup_ipv4_preference():
    orig_getaddrinfo = socket.getaddrinfo

    def _ipv4_first_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        try:
            return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
        except Exception:
            return orig_getaddrinfo(host, port, family, type, proto, flags)

    socket.getaddrinfo = _ipv4_first_getaddrinfo

_setup_ipv4_preference()

# Locate .env file in kisansathi/ or workspace root
_current_dir = Path(__file__).resolve().parent
_env_candidates = [
    _current_dir.parent / ".env",
    _current_dir / ".env",
    Path.cwd() / ".env",
]

for _env_file in _env_candidates:
    if _env_file.exists():
        load_dotenv(dotenv_path=_env_file, override=False)
        break
else:
    load_dotenv()  # Fallback to default search


class Settings(BaseModel):
    gemini_api_key: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = Field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.5-flash"))
    data_gov_api_key: str = Field(default_factory=lambda: os.getenv("DATA_GOV_API_KEY", ""))
    telegram_bot_token: str = Field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    alert_language: str = Field(default_factory=lambda: os.getenv("ALERT_LANGUAGE", "Hindi"))
    port: int = Field(default_factory=lambda: int(os.getenv("PORT", "8000")))

    def reload(self):
        """Reload configuration from environment variables."""
        for _env_file in _env_candidates:
            if _env_file.exists():
                load_dotenv(dotenv_path=_env_file, override=True)
                break
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        self.data_gov_api_key = os.getenv("DATA_GOV_API_KEY", "")
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.alert_language = os.getenv("ALERT_LANGUAGE", "Hindi")
        self.port = int(os.getenv("PORT", "8000"))


settings = Settings()
