"""
ClaimFast – Robust Groq API Client Wrapper

Provides:
- Resilient model execution with multi-key failover and rate-limit backoff.
- Strict JSON mode execution with raw response preservation.
- Comprehensive schema validation against the 9 ClaimFast extraction fields.
- Token consumption and millisecond latency tracking.
- Absolute secret protection (sanitized logs, alias-based tracking).
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

_code_dir = str(Path(__file__).resolve().parent)
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

from groq_config import GroqConfig
from groq_key_manager import AllCredentialsExhaustedError, Credential, GroqKeyManager

logger = logging.getLogger("ClaimFast.GroqClient")

ALLOWED_CLAIM_TYPES: Set[str] = {
    "own_damage",
    "third_party_liability",
    "theft",
    "total_loss",
    "glass_only",
    "not_a_claim",
}

ALLOWED_URGENCY_LEVELS: Set[str] = {"high", "medium", "low"}

CLAIMFAST_REQUIRED_FIELDS: Set[str] = {
    "claim_type",
    "urgency",
    "policy_number",
    "incident_date",
    "location",
    "vehicle_reg_no",
    "estimated_amount_inr",
    "injury_reported",
    "police_report_filed",
}

DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_claimfast_output(data: Any) -> List[str]:
    """
    Validates that a parsed JSON object conforms to the ClaimFast 9-field schema.
    Returns a list of error descriptions (empty list if valid).
    """
    errors: List[str] = []

    if not isinstance(data, dict):
        return ["Model output is not a JSON object/dictionary."]

    actual_keys = set(data.keys())
    missing = CLAIMFAST_REQUIRED_FIELDS - actual_keys
    unexpected = actual_keys - CLAIMFAST_REQUIRED_FIELDS

    if missing:
        errors.append(f"Missing required extraction fields: {sorted(list(missing))}")
    if unexpected:
        errors.append(f"Unexpected extra fields in response: {sorted(list(unexpected))}")

    # 1. claim_type
    ct = data.get("claim_type")
    if ct not in ALLOWED_CLAIM_TYPES:
        errors.append(f"Invalid claim_type: '{ct}'. Allowed: {sorted(list(ALLOWED_CLAIM_TYPES))}")

    # 2. urgency
    urg = data.get("urgency")
    if urg not in ALLOWED_URGENCY_LEVELS:
        errors.append(f"Invalid urgency: '{urg}'. Allowed: {sorted(list(ALLOWED_URGENCY_LEVELS))}")

    # 3. policy_number
    pol = data.get("policy_number")
    if pol is not None and not isinstance(pol, str):
        errors.append(f"policy_number must be string or null, got: {type(pol).__name__}")

    # 4. incident_date
    dt = data.get("incident_date")
    if dt is not None:
        if not isinstance(dt, str):
            errors.append(f"incident_date must be string or null, got: {type(dt).__name__}")
        elif not DATE_REGEX.match(dt):
            errors.append(f"incident_date must be YYYY-MM-DD format, got: '{dt}'")

    # 5. location
    loc = data.get("location")
    if loc is not None and not isinstance(loc, str):
        errors.append(f"location must be string or null, got: {type(loc).__name__}")

    # 6. vehicle_reg_no
    reg = data.get("vehicle_reg_no")
    if reg is not None:
        if not isinstance(reg, str):
            errors.append(f"vehicle_reg_no must be string or null, got: {type(reg).__name__}")
        elif re.search(r"\s", reg):
            errors.append(f"vehicle_reg_no contains forbidden whitespace: '{reg}'")

    # 7. estimated_amount_inr
    amt = data.get("estimated_amount_inr")
    if amt is not None:
        if isinstance(amt, bool) or not isinstance(amt, int):
            errors.append(f"estimated_amount_inr must be integer or null, got: {type(amt).__name__}")
        elif amt < 0:
            errors.append(f"estimated_amount_inr cannot be negative: {amt}")

    # 8. injury_reported
    inj = data.get("injury_reported")
    if inj is not None and not isinstance(inj, bool):
        errors.append(f"injury_reported must be boolean or null, got: {type(inj).__name__}")

    # 9. police_report_filed
    pol_rep = data.get("police_report_filed")
    if pol_rep is not None and not isinstance(pol_rep, bool):
        errors.append(f"police_report_filed must be boolean or null, got: {type(pol_rep).__name__}")

    return errors


@dataclass
class GenerationResult:
    """Encapsulates the full result, metadata, and diagnostics of an LLM generation call."""
    success: bool
    raw_response: str
    parsed_json: Optional[Dict[str, Any]] = None
    parse_error: Optional[str] = None
    validation_errors: List[str] = field(default_factory=list)
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    latency_ms: float = 0.0
    model_name: str = ""
    credential_alias: str = ""
    status: str = "SUCCESS"  # SUCCESS, PARSE_ERROR, VALIDATION_ERROR, API_ERROR
    error_category: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result into a serializable dictionary for JSONL export."""
        return {
            "success": self.success,
            "raw_response": self.raw_response,
            "parsed_json": self.parsed_json,
            "parse_error": self.parse_error,
            "validation_errors": self.validation_errors,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": round(self.latency_ms, 2),
            "model_name": self.model_name,
            "credential_alias": self.credential_alias,
            "status": self.status,
            "error_category": self.error_category,
            "error_message": self.error_message,
        }


class GroqClient:
    """
    High-reliability Groq API client with multi-key rotation and rate-limit recovery.
    """

    def __init__(
        self,
        key_manager: Optional[GroqKeyManager] = None,
        config: Optional[GroqConfig] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ):
        if config is None:
            if key_manager is not None:
                self.config = key_manager.config
            else:
                self.config = GroqConfig.from_env()
        else:
            self.config = config

        if key_manager is None:
            self.key_manager = GroqKeyManager(self.config)
        else:
            self.key_manager = key_manager

        self.sleep_fn = sleep_fn if sleep_fn is not None else time.sleep

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = True,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        record_id: Optional[str] = None,
        prompt_strategy: Optional[str] = None,
    ) -> GenerationResult:
        """
        Execute completion with automatic credential rotation, error handling, and schema validation.
        """
        if self.key_manager.total_configured == 0:
            return GenerationResult(
                success=False,
                raw_response="",
                status="API_ERROR",
                error_category="NO_CREDENTIALS",
                error_message="No Groq API credentials configured.",
                model_name=self.config.model,
            )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        request_kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            request_kwargs["response_format"] = {"type": "json_object"}

        attempt = 0
        max_attempts = max(1, self.config.max_retries + 1)
        last_error_alias = ""
        last_error_category = None
        last_error_msg = None

        while attempt < max_attempts:
            attempt += 1

            # 1. Select the best available credential
            try:
                cred, wait_time = self.key_manager.select_active_credential()
            except AllCredentialsExhaustedError as e:
                clean_err = self.config.sanitize_log(str(e))
                logger.error("All credentials exhausted: %s", clean_err)
                return GenerationResult(
                    success=False,
                    raw_response="",
                    status="API_ERROR",
                    error_category="ALL_CREDENTIALS_EXHAUSTED",
                    error_message=clean_err,
                    model_name=self.config.model,
                    credential_alias=last_error_alias,
                )

            # If all available keys are rate limited, wait the required time
            if wait_time > 0.0:
                logger.warning(
                    "All keys currently rate limited. Waiting %.2fs before retrying...",
                    wait_time,
                )
                self.sleep_fn(wait_time)

            client = cred.get_client()
            t0 = time.perf_counter()

            try:
                logger.info(
                    "Calling Groq API [attempt %d/%d, alias=%s, model=%s, record=%s]",
                    attempt,
                    max_attempts,
                    cred.alias,
                    self.config.model,
                    record_id or "N/A",
                )
                response = client.chat.completions.create(**request_kwargs)
                latency_ms = (time.perf_counter() - t0) * 1000.0

                # Record success on credential
                self.key_manager.record_success(cred.alias)

                # Extract response text
                raw_text = ""
                if response.choices and len(response.choices) > 0:
                    raw_text = response.choices[0].message.content or ""

                # Extract token usage
                input_tokens = None
                output_tokens = None
                total_tokens = None
                if getattr(response, "usage", None):
                    input_tokens = getattr(response.usage, "prompt_tokens", None)
                    output_tokens = getattr(response.usage, "completion_tokens", None)
                    total_tokens = getattr(response.usage, "total_tokens", None)

                # Parse JSON safely
                parsed_json = None
                parse_error = None
                try:
                    parsed_json = json.loads(raw_text)
                except Exception as pe:
                    parse_error = str(pe)
                    logger.warning(
                        "Model returned invalid JSON [record=%s, alias=%s]: %s",
                        record_id or "N/A",
                        cred.alias,
                        parse_error,
                    )
                    return GenerationResult(
                        success=False,
                        raw_response=raw_text,
                        parsed_json=None,
                        parse_error=parse_error,
                        validation_errors=[],
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                        latency_ms=latency_ms,
                        model_name=self.config.model,
                        credential_alias=cred.alias,
                        status="PARSE_ERROR",
                        error_category="JSON_DECODE_ERROR",
                        error_message=parse_error,
                    )

                # Validate against ClaimFast 9-field schema
                val_errors = validate_claimfast_output(parsed_json)
                status = "VALIDATION_ERROR" if val_errors else "SUCCESS"
                success = len(val_errors) == 0

                if val_errors:
                    logger.warning(
                        "Schema validation failed [record=%s, alias=%s]: %s",
                        record_id or "N/A",
                        cred.alias,
                        val_errors,
                    )

                return GenerationResult(
                    success=success,
                    raw_response=raw_text,
                    parsed_json=parsed_json,
                    parse_error=None,
                    validation_errors=val_errors,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency_ms,
                    model_name=self.config.model,
                    credential_alias=cred.alias,
                    status=status,
                    error_category="SCHEMA_VALIDATION_ERROR" if val_errors else None,
                    error_message=None if success else "; ".join(val_errors),
                )

            except Exception as exc:
                latency_ms = (time.perf_counter() - t0) * 1000.0
                last_error_alias = cred.alias
                err_type_name = type(exc).__name__
                raw_err_msg = str(exc)
                clean_err_msg = self.config.sanitize_log(raw_err_msg)

                # Inspect HTTP status code if present
                status_code = getattr(exc, "status_code", None)
                response_obj = getattr(exc, "response", None)
                if status_code is None and response_obj is not None:
                    status_code = getattr(response_obj, "status_code", None)

                # Case A: Authentication / Permission Denied (HTTP 401 / 403)
                if (
                    status_code in (401, 403)
                    or "AuthenticationError" in err_type_name
                    or "PermissionDenied" in err_type_name
                ):
                    self.key_manager.record_auth_failure(cred.alias, clean_err_msg)
                    last_error_category = "AUTH_FAILURE"
                    last_error_msg = clean_err_msg
                    logger.error(
                        "Auth failure on %s. Rotating to next key immediately.", cred.alias
                    )
                    # Auth failure does not consume normal retry quota; try next available key
                    attempt -= 1
                    continue

                # Case B: Rate Limit (HTTP 429)
                elif status_code == 429 or "RateLimit" in err_type_name:
                    resp_headers = {}
                    if response_obj is not None:
                        resp_headers = dict(getattr(response_obj, "headers", {}))

                    reset_delay = self.key_manager.record_rate_limit(
                        cred.alias,
                        headers=resp_headers,
                        error_msg=clean_err_msg,
                    )
                    last_error_category = "RATE_LIMIT"
                    last_error_msg = clean_err_msg

                    # Check if another healthy credential exists right now
                    other_healthy = any(
                        c.is_available() for a, c in self.key_manager.credentials.items() if a != cred.alias
                    )
                    if other_healthy:
                        logger.info(
                            "Rate limit on %s. Other healthy keys exist; falling back immediately.",
                            cred.alias,
                        )
                        attempt -= 1  # Key switch does not penalize retry counter
                        continue
                    else:
                        # All keys rate limited; pause before next retry
                        logger.warning(
                            "Rate limit on %s and no other healthy keys. Sleeping %.2fs...",
                            cred.alias,
                            reset_delay,
                        )
                        self.sleep_fn(min(reset_delay, 60.0))
                        continue

                # Case C: Network Timeout (APITimeoutError)
                elif "Timeout" in err_type_name:
                    self.key_manager.record_transient_error(cred.alias, clean_err_msg)
                    last_error_category = "TIMEOUT"
                    last_error_msg = clean_err_msg
                    backoff = min(30.0, 1.0 * (2 ** (attempt - 1)))
                    logger.warning(
                        "Timeout on %s. Backing off for %.2fs [attempt %d/%d].",
                        cred.alias,
                        backoff,
                        attempt,
                        max_attempts,
                    )
                    self.sleep_fn(backoff)
                    continue

                # Case D: Server 5xx or Connection Error (Transient)
                else:
                    self.key_manager.record_transient_error(cred.alias, clean_err_msg)
                    last_error_category = "TRANSIENT_ERROR"
                    last_error_msg = clean_err_msg
                    backoff = min(30.0, 1.0 * (2 ** (attempt - 1)))
                    logger.warning(
                        "Transient error (%s) on %s. Backing off for %.2fs [attempt %d/%d]: %s",
                        err_type_name,
                        cred.alias,
                        backoff,
                        attempt,
                        max_attempts,
                        clean_err_msg,
                    )
                    self.sleep_fn(backoff)
                    continue

        # If loop finishes without returning, retries were exhausted
        return GenerationResult(
            success=False,
            raw_response="",
            status="API_ERROR",
            error_category=last_error_category or "MAX_RETRIES_EXCEEDED",
            error_message=last_error_msg or "Exceeded maximum retry attempts.",
            model_name=self.config.model,
            credential_alias=last_error_alias,
        )

