"""
ClaimFast – Secure Groq API Configuration Loader and Validator

Handles secure loading of credentials from environment variables and local .env files.
Guarantees zero leakage of secrets: API keys are never printed, logged, or exposed.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# Models officially known to support Groq JSON Object mode (response_format={'type': 'json_object'})
KNOWN_JSON_SUPPORTED_MODELS = {
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
    "deepseek-r1-distill-llama-70b",
    "qwen/qwen3.8-27b",
}


def load_env_file(env_path: Optional[Path] = None) -> Dict[str, str]:
    """
    Safely parse a .env file without external dependencies.
    Existing os.environ values take precedence over values in .env.
    """
    loaded: Dict[str, str] = {}
    candidates: List[Path] = []

    if env_path:
        candidates.append(env_path)
    else:
        # Check standard search locations relative to this file and CWD
        current_dir = Path(__file__).resolve().parent
        candidates.extend([
            current_dir.parent / ".env",          # CS1_ClaimFast/.env
            current_dir.parent.parent / ".env",   # LLM_Case_Studies/.env
            Path.cwd() / ".env",                  # Current working directory .env
        ])

    for target in candidates:
        if target.is_file():
            try:
                with open(target, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("'\"")
                            if k:
                                loaded[k] = v
                                # Only set into os.environ if not already present
                                if k not in os.environ:
                                    os.environ[k] = v
                break  # Stop after reading the first matching .env file
            except Exception:
                continue

    return loaded


@dataclass
class GroqConfig:
    """
    Holds validated, multi-key configuration for the Groq API.
    Raw keys are stored internally but strictly omitted from repr and str.
    """
    keys: Dict[str, str] = field(default_factory=dict)  # {"key_1": "gsk_...", ...}
    model: str = "llama-3.3-70b-versatile"
    max_retries: int = 3
    timeout: int = 60

    @classmethod
    def from_env(cls, env_path: Optional[Path] = None) -> GroqConfig:
        """
        Load configuration from os.environ, falling back to .env if needed.
        """
        load_env_file(env_path)

        keys: Dict[str, str] = {}
        # Dynamically discover all configured key slots: GROQ_API_KEY_1, GROQ_API_KEY_2, ...
        for slot in range(1, 21):
            val = os.getenv(f"GROQ_API_KEY_{slot}", "").strip()
            if val and not val.startswith("gsk_your_first_groq"):
                keys[f"key_{slot}"] = val

        # Backward-compatibility fallback: if GROQ_API_KEY is set and slot 1 was empty
        if "key_1" not in keys:
            fallback = os.getenv("GROQ_API_KEY", "").strip()
            if fallback and not fallback.startswith("gsk_your_first_groq"):
                keys["key_1"] = fallback

        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
        if not model:
            model = "llama-3.3-70b-versatile"

        try:
            max_retries = int(os.getenv("GROQ_MAX_RETRIES", "3"))
        except ValueError:
            max_retries = 3

        try:
            timeout = int(os.getenv("GROQ_TIMEOUT", "60"))
        except ValueError:
            timeout = 60

        return cls(
            keys=keys,
            model=model,
            max_retries=max_retries,
            timeout=timeout,
        )

    def validate(self) -> List[str]:
        """
        Validates configuration without making any network requests.
        Returns a list of validation error messages, or an empty list if valid.
        """
        errors: List[str] = []

        if not self.keys:
            errors.append(
                "No Groq API keys configured. Set at least GROQ_API_KEY_1 in your .env or environment."
            )

        for alias, key in self.keys.items():
            if not isinstance(key, str) or len(key.strip()) < 10:
                errors.append(f"Credential '{alias}' is invalid or too short.")
            if re.search(r"\s", key):
                errors.append(f"Credential '{alias}' contains forbidden whitespace.")

        if not self.model or not isinstance(self.model, str):
            errors.append("GROQ_MODEL must be a non-empty string.")

        if self.max_retries < 0:
            errors.append("GROQ_MAX_RETRIES must be non-negative.")

        if self.timeout <= 0:
            errors.append("GROQ_TIMEOUT must be greater than 0.")

        return errors

    def check_model_json_compatibility(self) -> Optional[str]:
        """
        Returns a warning message if the configured model is not in the known JSON-mode allowlist.
        Does not crash, but reports the potential incompatibility.
        """
        if self.model not in KNOWN_JSON_SUPPORTED_MODELS:
            return (
                f"Configured model '{self.model}' is not in the verified Groq JSON-mode allowlist: "
                f"{sorted(list(KNOWN_JSON_SUPPORTED_MODELS))}. Structured JSON extraction may fail."
            )
        return None

    def sanitize_log(self, text: str) -> str:
        """
        Scrub all configured raw API key values from any text string.
        Replaces each with '[REDACTED_key_X]'.
        """
        if not text:
            return text
        sanitized = text
        for alias, key_val in self.keys.items():
            if key_val and len(key_val) > 4:
                sanitized = sanitized.replace(key_val, f"[REDACTED_{alias}]")
        # Also redact any potential gsk_ token patterns
        sanitized = re.sub(r"gsk_[a-zA-Z0-9]{20,}", "[REDACTED_GROQ_KEY]", sanitized)
        return sanitized

    def __repr__(self) -> str:
        configured_aliases = list(self.keys.keys())
        return (
            f"GroqConfig(configured_keys={configured_aliases}, "
            f"model='{self.model}', max_retries={self.max_retries}, timeout={self.timeout})"
        )

    def __str__(self) -> str:
        return self.__repr__()

