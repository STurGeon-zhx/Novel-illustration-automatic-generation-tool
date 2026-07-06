import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_key: str
    text_model: str
    image_model: str
    image_size: str
    image_return_base64: bool
    data_dir: Path
    database_path: Path
    outputs_dir: Path
    timeout_seconds: int
    max_retries: int
    legacy_owner_id: str


def load_settings():
    _load_env_file(Path(__file__).resolve().parents[2] / ".env")
    _load_env_file(Path(".env"))
    data_dir = Path(os.getenv("APP_DATA_DIR", "data"))
    return Settings(
        base_url=os.getenv("OPENAI_BASE_URL", "https://apihub.agnes-ai.com/v1"),
        api_key=os.getenv("OPENAI_API_KEY", ""),
        text_model=os.getenv("TEXT_MODEL", "agnes-2.0-flash"),
        image_model=os.getenv("IMAGE_MODEL", "agnes-image-2.1-flash"),
        image_size=os.getenv("IMAGE_SIZE", "1024x1024"),
        image_return_base64=_env_bool("IMAGE_RETURN_BASE64", True),
        data_dir=data_dir,
        database_path=Path(os.getenv("DATABASE_PATH", data_dir / "app.db")),
        outputs_dir=Path(os.getenv("OUTPUTS_DIR", "outputs")),
        timeout_seconds=int(os.getenv("MODEL_TIMEOUT_SECONDS", "120")),
        max_retries=int(os.getenv("MODEL_MAX_RETRIES", "5")),
        legacy_owner_id=os.getenv("LEGACY_OWNER_ID", "").strip(),
    )


def _load_env_file(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _env_bool(key, default):
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
