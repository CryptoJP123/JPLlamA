from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse


DEFAULT_OBSIDIAN_VAULT = Path(
    "/Users/jeanpierrelang/Library/Mobile Documents/com~apple~CloudDocs/JP Obsidian Vault"
)


def _default_obsidian_vault() -> Path:
    explicit = os.getenv("JPLLAMA_OBSIDIAN_VAULT")
    if explicit:
        return Path(explicit).expanduser()
    return DEFAULT_OBSIDIAN_VAULT

@dataclass
class Settings:

    # Ollama

    ollama_url: str = "http://127.0.0.1:11434"

    text_model: str = "qwen3:8b"

    reasoning_model: str = "deepseek-r1:8b"

    polish_model: str = "gemma4:latest"

    vision_model: str = "qwen3-vl:8b"
    ollama_timeout_seconds: int = 1800
    ollama_max_retries: int = 2
    ollama_retry_backoff_seconds: float = 1.0

    # Presenton

    presenton_url: str = "http://127.0.0.1:5001"

    presenton_username: str = "jaempilang@gmail.com"

    presenton_password: str = "FuckA19*"

    # When None, JPLlamA omits template and lets Presenton choose its built-in default.
    presenton_template: Optional[str] = None
    # Built-in fallback used when JP does not specify a template.
    presenton_default_template: str = "general"
    # Optional recipe-to-template map (e.g. {"executive": "template-v2-..."}).
    presenton_template_recipes: Dict[str, str] = field(default_factory=dict)

    presenton_language: str = "English"
    presenton_timeout_seconds: int = 120
    presenton_max_retries: int = 2
    presenton_retry_backoff_seconds: float = 1.0

    # Open WebUI (optional watcher integration)

    openwebui_url: str = "http://127.0.0.1:3000"

    # SearXNG (web search backend for Open WebUI)

    searxng_url: str = "http://127.0.0.1:8081"

    # Obsidian

    obsidian_vault: Path = _default_obsidian_vault()

    # General

    project_name: str = "JPLlamA"

    debug: bool = True
    output_dir: Path = Path("output")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    if not raw:
        return default
    return Path(raw).expanduser()


def _env_optional_str(name: str, default: Optional[str] = None) -> Optional[str]:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip()
    if not value:
        return None
    return value


def _env_json_dict(name: str) -> Dict[str, str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    result: Dict[str, str] = {}
    for key, value in payload.items():
        key_text = str(key).strip().lower()
        value_text = str(value).strip()
        if key_text and value_text:
            result[key_text] = value_text
    return result


def _normalise_template_identifier(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def resolve_presenton_template(
    *,
    explicit_template: Optional[str] = None,
    recipe_name: Optional[str] = None,
    current: Optional[Settings] = None,
) -> Optional[str]:
    active = current or settings

    chosen = _normalise_template_identifier(explicit_template)
    if chosen:
        return chosen

    recipe = _normalise_template_identifier(recipe_name)
    if recipe:
        mapped = active.presenton_template_recipes.get(recipe.lower())
        mapped = _normalise_template_identifier(mapped)
        if mapped:
            return mapped

    return _normalise_template_identifier(active.presenton_template)


def _valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def load_settings() -> Settings:
    return Settings(
        ollama_url=os.getenv("JPLLAMA_OLLAMA_URL", "http://127.0.0.1:11434"),
        text_model=os.getenv("JPLLAMA_TEXT_MODEL", "qwen3:8b"),
        reasoning_model=os.getenv("JPLLAMA_REASONING_MODEL", "deepseek-r1:8b"),
        polish_model=os.getenv("JPLLAMA_POLISH_MODEL", "gemma4:latest"),
        vision_model=os.getenv("JPLLAMA_VISION_MODEL", "qwen3-vl:8b"),
        ollama_timeout_seconds=_env_int("JPLLAMA_OLLAMA_TIMEOUT_SECONDS", 1800),
        ollama_max_retries=_env_int("JPLLAMA_OLLAMA_MAX_RETRIES", 2),
        ollama_retry_backoff_seconds=_env_float("JPLLAMA_OLLAMA_RETRY_BACKOFF_SECONDS", 1.0),
        presenton_url=os.getenv("JPLLAMA_PRESENTON_URL", "http://127.0.0.1:5001"),
        presenton_username=(os.getenv("JPLLAMA_PRESENTON_USERNAME", "jaempilang@gmail.com") or "jaempilang@gmail.com"),
        presenton_password=(os.getenv("JPLLAMA_PRESENTON_PASSWORD", "FuckA19*") or "FuckA19*"),
        presenton_template=_env_optional_str("JPLLAMA_PRESENTON_TEMPLATE", None),
        presenton_default_template=os.getenv("JPLLAMA_PRESENTON_DEFAULT_TEMPLATE", "general"),
        presenton_template_recipes=_env_json_dict("JPLLAMA_PRESENTON_TEMPLATE_RECIPES"),
        presenton_language=os.getenv("JPLLAMA_PRESENTON_LANGUAGE", "English"),
        presenton_timeout_seconds=_env_int("JPLLAMA_PRESENTON_TIMEOUT_SECONDS", 120),
        presenton_max_retries=_env_int("JPLLAMA_PRESENTON_MAX_RETRIES", 2),
        presenton_retry_backoff_seconds=_env_float("JPLLAMA_PRESENTON_RETRY_BACKOFF_SECONDS", 1.0),
        openwebui_url=os.getenv("JPLLAMA_OPENWEBUI_URL", "http://127.0.0.1:3000"),
        searxng_url=os.getenv("JPLLAMA_SEARXNG_URL", "http://127.0.0.1:8081"),
        obsidian_vault=_env_path("JPLLAMA_OBSIDIAN_VAULT", _default_obsidian_vault()),
        project_name=os.getenv("JPLLAMA_PROJECT_NAME", "JPLlamA"),
        debug=_env_bool("JPLLAMA_DEBUG", True),
        output_dir=_env_path("JPLLAMA_OUTPUT_DIR", Path("output")),
    )


def validate_settings(current: Settings) -> Dict[str, List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    if not _valid_url(current.ollama_url):
        errors.append(f"Invalid Ollama URL: {current.ollama_url}")
    if not _valid_url(current.presenton_url):
        errors.append(f"Invalid Presenton URL: {current.presenton_url}")
    if current.openwebui_url and not _valid_url(current.openwebui_url):
        errors.append(f"Invalid Open WebUI URL: {current.openwebui_url}")
    if current.searxng_url and not _valid_url(current.searxng_url):
        errors.append(f"Invalid SearXNG URL: {current.searxng_url}")

    vault = current.obsidian_vault.expanduser()
    if not vault.exists() or not vault.is_dir():
        errors.append(f"Vault path does not exist or is not a directory: {vault}")

    output_dir = current.output_dir.expanduser()
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        errors.append(f"Output directory is not writable: {output_dir} ({exc})")

    if not current.presenton_username:
        warnings.append("Presenton username is empty; presentation generation may fail to authenticate.")
    if not current.presenton_password:
        warnings.append("Presenton password is empty; presentation generation may fail to authenticate.")
    if current.ollama_timeout_seconds < 10:
        warnings.append("Ollama timeout is very low and may cause premature failures.")

    return {"errors": errors, "warnings": warnings}


settings = load_settings()