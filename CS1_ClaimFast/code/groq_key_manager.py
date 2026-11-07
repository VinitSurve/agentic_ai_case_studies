"""
ClaimFast – Secure Multi-API Key Manager and Credential Health Tracker

Manages up to 3 Groq API credentials with:
- Zero secret exposure in logs, traces, or string outputs.
- Key alias tracking: key_1, key_2, key_3.
- Automatic failover when a key exhausts or experiences auth failure.
- Groq HTTP 429 rate-limit header parsing and reset pacing.
- Authentication error isolation (HTTP 401/403 marks key permanently dead for the session).
- Bounded transient error backoff and recovery.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from groq_config import GroqConfig

logger = logging.getLogger("ClaimFast.GroqKeyManager")


class CredentialStatus(str, Enum):
    """Health status of an individual Groq API credential."""
    HEALTHY = "HEALTHY"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_FAILED = "AUTH_FAILED"
    DISABLED = "DISABLED"


def parse_rate_limit_reset(reset_str: Optional[str]) -> float:
    """
    Parse rate limit reset duration from headers (e.g. '6', '14.2s', '2m30s', '500ms').
    Returns duration in seconds. Defaults to 60.0 if unparseable or absent.
    """
    if not reset_str:
        return 60.0

    reset_str = str(reset_str).strip()

    # Direct float/integer
    try:
        return max(1.0, float(reset_str))
    except ValueError:
        pass

    total_seconds = 0.0
    matched = False

    # Check for minutes (e.g. '2m')
    m_match = re.search(r"(\d+(?:\.\d+)?)\s*m(?:in)?(?![a-z])", reset_str, re.IGNORECASE)
    if m_match:
        total_seconds += float(m_match.group(1)) * 60.0
        matched = True

    # Check for milliseconds (e.g. '500ms')
    ms_match = re.search(r"(\d+(?:\.\d+)?)\s*ms", reset_str, re.IGNORECASE)
    if ms_match:
        total_seconds += float(ms_match.group(1)) / 1000.0
        matched = True
    else:
        # Check for seconds (e.g. '14.2s')
        s_match = re.search(r"(\d+(?:\.\d+)?)\s*s(?:ec)?(?![a-z])", reset_str, re.IGNORECASE)
        if s_match:
            total_seconds += float(s_match.group(1))
            matched = True

    if matched:
        return max(1.0, total_seconds)

    return 60.0


@dataclass
class Credential:
    """
    Internal container for a single Groq API credential.
    Protects raw API key from string representation and logging.
    """
    alias: str
    _api_key: str = field(repr=False)
    status: CredentialStatus = CredentialStatus.HEALTHY
    rate_limit_reset_at: float = 0.0
    rate_limit_reason: Optional[str] = None
    total_requests: int = 0
    total_successes: int = 0
    total_rate_limits: int = 0
    total_auth_failures: int = 0
    total_transient_errors: int = 0
    last_used_at: Optional[float] = None
    _client: Optional[Any] = field(default=None, repr=False)
    client_factory: Optional[Callable[[str, int], Any]] = field(default=None, repr=False)
    timeout: int = 60

    def get_client(self) -> Any:
        """Lazily initialize and return the underlying Groq client."""
        if self._client is None:
            if self.client_factory is not None:
                self._client = self.client_factory(self._api_key, self.timeout)
            else:
                from groq import Groq
                self._client = Groq(
                    api_key=self._api_key,
                    timeout=float(self.timeout),
                    max_retries=0,  # We handle retries at the application level for multi-key coordination
                )
        return self._client

    def is_available(self, current_time: Optional[float] = None) -> bool:
        """Check if credential is ready to serve requests."""
        if self.status == CredentialStatus.AUTH_FAILED or self.status == CredentialStatus.DISABLED:
            return False

        if self.status == CredentialStatus.RATE_LIMITED:
            now = current_time if current_time is not None else time.time()
            if now >= self.rate_limit_reset_at:
                # Rate limit period has passed; auto-recover to healthy
                self.status = CredentialStatus.HEALTHY
                self.rate_limit_reset_at = 0.0
                self.rate_limit_reason = None
                return True
            return False

        return True

    def seconds_until_reset(self, current_time: Optional[float] = None) -> float:
        """Seconds remaining before rate limit resets."""
        now = current_time if current_time is not None else time.time()
        return max(0.0, self.rate_limit_reset_at - now)

    def __repr__(self) -> str:
        return (
            f"<Credential alias={self.alias} status={self.status.value} "
            f"requests={self.total_requests} successes={self.total_successes} "
            f"rate_limits={self.total_rate_limits} auth_failures={self.total_auth_failures}>"
        )

    def __str__(self) -> str:
        return self.__repr__()


class AllCredentialsExhaustedError(RuntimeError):
    """Raised when all configured Groq credentials are unavailable or dead."""
    pass


class GroqKeyManager:
    """
    Coordinates multi-key allocation, health monitoring, and fallback for Groq API keys.
    """

    def __init__(
        self,
        config: GroqConfig,
        client_factory: Optional[Callable[[str, int], Any]] = None,
    ):
        self.config = config
        self.client_factory = client_factory
        self.credentials: Dict[str, Credential] = {}
        self._active_index: int = 0

        # Initialize credentials for each non-empty key
        sorted_aliases = sorted(
            config.keys.keys(),
            key=lambda x: int(x.split("_")[1]) if "_" in x and x.split("_")[1].isdigit() else 99
        )

        for alias in sorted_aliases:
            key_val = config.keys[alias]
            self.credentials[alias] = Credential(
                alias=alias,
                _api_key=key_val,
                status=CredentialStatus.HEALTHY,
                client_factory=client_factory,
                timeout=config.timeout,
            )

        self._alias_list: List[str] = list(self.credentials.keys())

    @property
    def total_configured(self) -> int:
        return len(self.credentials)

    @property
    def configured_aliases(self) -> List[str]:
        return list(self._alias_list)

    def get_credential(self, alias: str) -> Optional[Credential]:
        return self.credentials.get(alias)

    def select_active_credential(self, current_time: Optional[float] = None) -> Tuple[Credential, float]:
        """
        Selects the best available credential.
        If the primary credential is rate-limited or failed, seamlessly falls back to the next healthy key.
        Returns (credential, wait_time_seconds). If wait_time_seconds > 0, all keys are temporarily rate-limited.
        Raises AllCredentialsExhaustedError if all keys are permanently dead (auth failed/disabled).
        """
        if not self.credentials:
            raise AllCredentialsExhaustedError(
                "No Groq API credentials configured. Set GROQ_API_KEY_1 in .env"
            )

        now = current_time if current_time is not None else time.time()
        num_keys = len(self._alias_list)

        # 1. Search starting from current active index for an available healthy key
        for offset in range(num_keys):
            idx = (self._active_index + offset) % num_keys
            alias = self._alias_list[idx]
            cred = self.credentials[alias]
            if cred.is_available(now):
                self._active_index = idx
                return cred, 0.0

        # 2. Check if any keys are merely rate-limited (recoverable) vs all dead
        rate_limited_creds = [
            c for c in self.credentials.values()
            if c.status == CredentialStatus.RATE_LIMITED
        ]

        if not rate_limited_creds:
            statuses = {c.alias: c.status.value for c in self.credentials.values()}
            raise AllCredentialsExhaustedError(
                f"All configured Groq API keys are permanently unavailable: {statuses}"
            )

        # 3. All available keys are currently rate-limited. Select the one that resets earliest.
        earliest_cred = min(rate_limited_creds, key=lambda c: c.rate_limit_reset_at)
        wait_time = earliest_cred.seconds_until_reset(now)
        return earliest_cred, wait_time

    def record_success(self, alias: str) -> None:
        """Record successful API response for the given credential alias."""
        cred = self.credentials.get(alias)
        if cred:
            cred.total_requests += 1
            cred.total_successes += 1
            cred.last_used_at = time.time()
            cred.status = CredentialStatus.HEALTHY
            cred.rate_limit_reset_at = 0.0
            cred.rate_limit_reason = None

    def record_auth_failure(self, alias: str, error_msg: str) -> None:
        """
        Handle HTTP 401/403. Marks credential as permanently dead for the session.
        Logs credential alias only, never secret value.
        """
        cred = self.credentials.get(alias)
        if cred:
            cred.total_requests += 1
            cred.total_auth_failures += 1
            cred.last_used_at = time.time()
            cred.status = CredentialStatus.AUTH_FAILED
            clean_msg = self.config.sanitize_log(error_msg)
            logger.error(
                "Groq credential '%s' failed authentication (HTTP 401/403). "
                "Marking permanently disabled for this run. Details: %s",
                alias,
                clean_msg,
            )
            # Advance active index to next available key
            self._advance_index()

    def record_rate_limit(
        self,
        alias: str,
        retry_after_header: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        error_msg: Optional[str] = None,
    ) -> float:
        """
        Handle HTTP 429. Calculates reset duration from Groq headers.
        Marks credential as RATE_LIMITED and advances to next key if available.
        Returns the reset delay in seconds.
        """
        cred = self.credentials.get(alias)
        if not cred:
            return 60.0

        cred.total_requests += 1
        cred.total_rate_limits += 1
        cred.last_used_at = time.time()
        cred.status = CredentialStatus.RATE_LIMITED

        reset_val: Optional[str] = retry_after_header

        if not reset_val and headers:
            # Check Groq-specific rate limit reset headers
            for h in (
                "retry-after",
                "x-ratelimit-reset-requests",
                "x-ratelimit-reset-tokens",
                "x-ratelimit-reset",
            ):
                if h in headers:
                    reset_val = headers[h]
                    break
                # Case-insensitive header lookup
                for k, v in headers.items():
                    if k.lower() == h:
                        reset_val = v
                        break
                if reset_val:
                    break

        duration = parse_rate_limit_reset(reset_val)
        cred.rate_limit_reset_at = time.time() + duration
        cred.rate_limit_reason = "rate_limit_exceeded (HTTP 429)"

        logger.warning(
            "Groq credential '%s' hit rate limit (HTTP 429). Paused for %.2fs until epoch %.1f.",
            alias,
            duration,
            cred.rate_limit_reset_at,
        )

        # Advance pointer to next key so subsequent requests immediately use other available keys
        self._advance_index()
        return duration

    def record_transient_error(self, alias: str, error_msg: str) -> None:
        """Record transient 5xx or network error."""
        cred = self.credentials.get(alias)
        if cred:
            cred.total_requests += 1
            cred.total_transient_errors += 1
            cred.last_used_at = time.time()
            clean_msg = self.config.sanitize_log(error_msg)
            logger.warning("Groq credential '%s' encountered transient error: %s", alias, clean_msg)

    def _advance_index(self) -> None:
        """Advance index to the next credential slot."""
        if self._alias_list:
            self._active_index = (self._active_index + 1) % len(self._alias_list)

    def get_health_summary(self) -> Dict[str, Dict[str, Any]]:
        """
        Returns a clean dictionary of credential health statistics.
        Contains NO API keys or sensitive data.
        """
        summary = {}
        for alias, cred in self.credentials.items():
            summary[alias] = {
                "status": cred.status.value,
                "total_requests": cred.total_requests,
                "total_successes": cred.total_successes,
                "total_rate_limits": cred.total_rate_limits,
                "total_auth_failures": cred.total_auth_failures,
                "total_transient_errors": cred.total_transient_errors,
                "seconds_until_reset": round(cred.seconds_until_reset(), 2),
                "is_available": cred.is_available(),
            }
        return summary

