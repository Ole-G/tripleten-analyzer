"""Configuration loader that merges YAML settings with environment variables."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

_config = None


def get_project_root() -> Path:
    """Return the absolute path to the project root directory."""
    return Path(__file__).resolve().parent.parent


def load_config(config_path: str = None) -> dict:
    """
    Load configuration from YAML and environment variables.

    API keys are resolved from the env var names specified in the YAML.
    All relative paths are resolved to absolute paths based on project root.
    The result is cached after the first call.
    """
    global _config
    if _config is not None:
        return _config

    project_root = get_project_root()

    # Load .env file
    dotenv_path = project_root / ".env"
    load_dotenv(dotenv_path)

    # Load YAML
    if config_path is None:
        config_path = project_root / "config" / "config.yaml"

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Resolve paths to absolute
    for key in [
        "source_dir", "raw_dir", "enriched_dir", "output_dir",
        "logs_dir", "integrations_file",
    ]:
        if key in config.get("paths", {}):
            config["paths"][key] = str(project_root / config["paths"][key])

    # Resolve API keys from env vars
    config["youtube"]["api_key"] = os.environ.get(
        config["youtube"]["api_key_env"], ""
    )
    config["llm"]["anthropic_key"] = os.environ.get(
        config["llm"]["anthropic_key_env"], ""
    )
    config["llm"]["openai_key"] = os.environ.get(
        config["llm"]["openai_key_env"], ""
    )

    _config = config
    return config


def reset_config():
    """Reset cached config (useful for testing)."""
    global _config
    _config = None
