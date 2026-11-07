"""
ClaimFast – Unit Test Suite for Multi-Key Groq API Infrastructure

Verifies all 12 key scenarios using offline mocks (zero live API calls):
1. Single configured key execution.
2. Multi-key configuration and rotation.
3. Missing key handling and empty configuration error.
4. Invalid configuration detection (timeouts, retries, whitespace).
5. Authentication failure (HTTP 401/403) triggering immediate fallback to key_2.
6. Rate limit (HTTP 429) header parsing and fallback to key_2.
7. Transient HTTP 500 error retry with bounded exponential backoff.
8. Network timeout (APITimeoutError) handling.
9. Malformed JSON response preservation and parse error handling.
10. Valid JSON response schema validation and token/latency capture.
11. Evaluation runner resumability and skipping of completed jobs.
12. Strict security audit: zero leakage of raw API keys in logs, repr, or outputs.
"""

from __future__ import annotations

import io
import json
import logging
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

_code_dir = str(Path(__file__).resolve().parent)
if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

import httpx
from groq import APITimeoutError, AuthenticationError, InternalServerError, RateLimitError

from evaluation_runner import EvaluationRunner, format_prompt, get_completed_job_ids
from groq_client import GenerationResult, GroqClient, validate_claimfast_output
from groq_config import GroqConfig
from groq_key_manager import AllCredentialsExhaustedError, CredentialStatus, GroqKeyManager, parse_rate_limit_reset


def make_mock_completion(
    content: str,
    prompt_tokens: int = 120,
    completion_tokens: int = 45,
) -> MagicMock:
    """Helper to build a mocked Groq ChatCompletion response."""
    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_resp.choices = [mock_choice]
    mock_resp.usage.prompt_tokens = prompt_tokens
    mock_resp.usage.completion_tokens = completion_tokens
    mock_resp.usage.total_tokens = prompt_tokens + completion_tokens
    return mock_resp


VALID_CLAIM_JSON = {
    "claim_type": "own_damage",
    "urgency": "medium",
    "policy_number": "POL-2026-9901",
    "incident_date": "2026-04-15",
    "location": "Bandra West, Mumbai",
    "vehicle_reg_no": "MH02AB1234",
    "estimated_amount_inr": 25000,
    "injury_reported": False,
    "police_report_filed": True,
}


class TestGroqSystem(unittest.TestCase):
    """12 Comprehensive offline tests for ClaimFast Groq API system."""

    def test_01_one_configured_key_works(self):
        """Scenario 1: Single configured key functions properly."""
        config = GroqConfig(
            keys={"key_1": "gsk_testkey_1_11111111111111111111"},
            model="llama-3.3-70b-versatile",
        )
        self.assertEqual(config.validate(), [])

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = make_mock_completion(
            json.dumps(VALID_CLAIM_JSON)
        )

        mgr = GroqKeyManager(config, client_factory=lambda key, timeout: mock_client)
        self.assertEqual(mgr.total_configured, 1)
        self.assertEqual(mgr.configured_aliases, ["key_1"])

        client = GroqClient(key_manager=mgr, config=config)
        res = client.generate("Analyze this claim.")

        self.assertTrue(res.success)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.credential_alias, "key_1")
        self.assertEqual(res.parsed_json["claim_type"], "own_damage")
        self.assertEqual(mgr.credentials["key_1"].total_successes, 1)

    def test_02_multiple_configured_keys(self):
        """Scenario 2: Multiple configured keys are correctly discovered and accessible."""
        config = GroqConfig(
            keys={
                "key_1": "gsk_key1_11111111111111111111",
                "key_2": "gsk_key2_22222222222222222222",
                "key_3": "gsk_key3_33333333333333333333",
            },
            model="llama-3.3-70b-versatile",
        )
        self.assertEqual(config.validate(), [])

        mgr = GroqKeyManager(config)
        self.assertEqual(mgr.total_configured, 3)
        self.assertEqual(mgr.configured_aliases, ["key_1", "key_2", "key_3"])

        cred1, wait1 = mgr.select_active_credential()
        self.assertEqual(cred1.alias, "key_1")
        self.assertEqual(wait1, 0.0)

    def test_03_missing_keys_handled_properly(self):
        """Scenario 3: Empty slots ignored; completely empty configuration reports error."""
        # Partially empty slots
        config = GroqConfig(
            keys={
                "key_1": "gsk_key1_11111111111111111111",
                "key_3": "gsk_key3_33333333333333333333",
            }
        )
        mgr = GroqKeyManager(config)
        self.assertEqual(mgr.total_configured, 2)
        self.assertEqual(mgr.configured_aliases, ["key_1", "key_3"])

        # Completely empty slots
        empty_config = GroqConfig(keys={})
        errs = empty_config.validate()
        self.assertTrue(any("No Groq API keys" in e for e in errs))

        empty_mgr = GroqKeyManager(empty_config)
        with self.assertRaises(AllCredentialsExhaustedError):
            empty_mgr.select_active_credential()

    def test_04_invalid_configuration_handled(self):
        """Scenario 4: Invalid configuration values caught by validator."""
        bad_config = GroqConfig(
            keys={"key_1": "short", "key_2": "gsk_has whitespace_123456789"},
            model="",
            max_retries=-2,
            timeout=0,
        )
        errors = bad_config.validate()
        self.assertTrue(any("too short" in e for e in errors))
        self.assertTrue(any("whitespace" in e for e in errors))
        self.assertTrue(any("GROQ_MODEL" in e for e in errors))
        self.assertTrue(any("GROQ_MAX_RETRIES" in e for e in errors))
        self.assertTrue(any("GROQ_TIMEOUT" in e for e in errors))

    def test_05_auth_failure_triggers_fallback_to_key_2(self):
        """Scenario 5: HTTP 401/403 permanently disables key_1 and immediately falls back to key_2."""
        config = GroqConfig(
            keys={
                "key_1": "gsk_bad_auth_key_1111111111111",
                "key_2": "gsk_good_auth_key_2222222222222",
            }
        )

        # Mock clients per key
        client_k1 = MagicMock()
        http_req = httpx.Request("POST", "https://api.groq.com/chat")
        http_resp_401 = httpx.Response(401, request=http_req)
        client_k1.chat.completions.create.side_effect = AuthenticationError(
            "Invalid API Key", response=http_resp_401, body=None
        )

        client_k2 = MagicMock()
        client_k2.chat.completions.create.return_value = make_mock_completion(
            json.dumps(VALID_CLAIM_JSON)
        )

        def mock_factory(key: str, timeout: int):
            if "bad_auth" in key:
                return client_k1
            return client_k2

        mgr = GroqKeyManager(config, client_factory=mock_factory)
        client = GroqClient(key_manager=mgr, config=config)

        res = client.generate("Triage message")

        # Key 1 must be marked AUTH_FAILED; request must succeed on key_2
        self.assertTrue(res.success)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.credential_alias, "key_2")
        self.assertEqual(mgr.credentials["key_1"].status, CredentialStatus.AUTH_FAILED)
        self.assertEqual(mgr.credentials["key_2"].status, CredentialStatus.HEALTHY)
        self.assertEqual(mgr.credentials["key_2"].total_successes, 1)

    def test_06_rate_limit_triggers_fallback_to_key_2_and_parses_headers(self):
        """Scenario 6: HTTP 429 parses reset duration, marks key_1 RATE_LIMITED, and falls back to key_2."""
        # Test header parser directly
        self.assertEqual(parse_rate_limit_reset("14.2s"), 14.2)
        self.assertEqual(parse_rate_limit_reset("2m30s"), 150.0)
        self.assertEqual(parse_rate_limit_reset("500ms"), 1.0)  # min bound 1.0s
        self.assertEqual(parse_rate_limit_reset("10"), 10.0)
        self.assertEqual(parse_rate_limit_reset(None), 60.0)

        config = GroqConfig(
            keys={
                "key_1": "gsk_rl_key_111111111111111111111",
                "key_2": "gsk_ok_key_222222222222222222222",
            }
        )

        http_req = httpx.Request("POST", "https://api.groq.com/chat")
        http_resp_429 = httpx.Response(
            429,
            headers={"retry-after": "18.5s", "x-ratelimit-reset-requests": "18.5s"},
            request=http_req,
        )

        client_k1 = MagicMock()
        client_k1.chat.completions.create.side_effect = RateLimitError(
            "Rate limit exceeded", response=http_resp_429, body=None
        )

        client_k2 = MagicMock()
        client_k2.chat.completions.create.return_value = make_mock_completion(
            json.dumps(VALID_CLAIM_JSON)
        )

        def mock_factory(key: str, timeout: int):
            if "rl_key" in key:
                return client_k1
            return client_k2

        mgr = GroqKeyManager(config, client_factory=mock_factory)
        client = GroqClient(key_manager=mgr, config=config)

        res = client.generate("Triage message")

        self.assertTrue(res.success)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.credential_alias, "key_2")
        self.assertEqual(mgr.credentials["key_1"].status, CredentialStatus.RATE_LIMITED)
        self.assertGreater(mgr.credentials["key_1"].rate_limit_reset_at, time.time())
        self.assertEqual(mgr.credentials["key_2"].total_successes, 1)

    def test_07_transient_500_retries_with_exponential_backoff(self):
        """Scenario 7: Transient HTTP 500 retries with exponential backoff and succeeds."""
        config = GroqConfig(
            keys={"key_1": "gsk_test_key_111111111111111111"},
            max_retries=2,
        )

        http_req = httpx.Request("POST", "https://api.groq.com/chat")
        http_resp_500 = httpx.Response(500, request=http_req)

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            InternalServerError("Internal server error", response=http_resp_500, body=None),
            make_mock_completion(json.dumps(VALID_CLAIM_JSON)),
        ]

        sleeps: list[float] = []
        mgr = GroqKeyManager(config, client_factory=lambda k, t: mock_client)
        client = GroqClient(key_manager=mgr, config=config, sleep_fn=sleeps.append)

        res = client.generate("Triage message")

        self.assertTrue(res.success)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 1.0, places=1)
        self.assertEqual(mgr.credentials["key_1"].total_transient_errors, 1)
        self.assertEqual(mgr.credentials["key_1"].total_successes, 1)

    def test_08_network_timeout_handled_safely(self):
        """Scenario 8: Network timeout (APITimeoutError) handled as transient error with backoff."""
        config = GroqConfig(
            keys={"key_1": "gsk_test_key_111111111111111111"},
            max_retries=2,
        )

        http_req = httpx.Request("POST", "https://api.groq.com/chat")
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            APITimeoutError(http_req),
            make_mock_completion(json.dumps(VALID_CLAIM_JSON)),
        ]

        sleeps: list[float] = []
        mgr = GroqKeyManager(config, client_factory=lambda k, t: mock_client)
        client = GroqClient(key_manager=mgr, config=config, sleep_fn=sleeps.append)

        res = client.generate("Triage message")

        self.assertTrue(res.success)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(len(sleeps), 1)
        self.assertEqual(mgr.credentials["key_1"].total_transient_errors, 1)

    def test_09_malformed_json_preserved_and_flagged(self):
        """Scenario 9: Malformed JSON preserved without crashing; flagged as PARSE_ERROR."""
        config = GroqConfig(keys={"key_1": "gsk_test_key_111111111111111111"})
        malformed_text = "Here is your claim extraction: {claim_type: 'own_damage', missing_quotes: true}"

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = make_mock_completion(malformed_text)

        mgr = GroqKeyManager(config, client_factory=lambda k, t: mock_client)
        client = GroqClient(key_manager=mgr, config=config)

        res = client.generate("Triage message")

        self.assertFalse(res.success)
        self.assertEqual(res.status, "PARSE_ERROR")
        self.assertEqual(res.raw_response, malformed_text)
        self.assertIsNone(res.parsed_json)
        self.assertIsNotNone(res.parse_error)
        self.assertEqual(res.error_category, "JSON_DECODE_ERROR")

    def test_10_valid_json_parsed_schema_validated_and_metrics(self):
        """Scenario 10: Valid JSON parsed, conforms to 9-field schema, records token and latency metrics."""
        config = GroqConfig(keys={"key_1": "gsk_test_key_111111111111111111"})
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = make_mock_completion(
            json.dumps(VALID_CLAIM_JSON), prompt_tokens=180, completion_tokens=55
        )

        mgr = GroqKeyManager(config, client_factory=lambda k, t: mock_client)
        client = GroqClient(key_manager=mgr, config=config)

        res = client.generate("Triage message")

        self.assertTrue(res.success)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.validation_errors, [])
        self.assertEqual(res.parsed_json["claim_type"], "own_damage")
        self.assertEqual(res.parsed_json["urgency"], "medium")
        self.assertEqual(res.input_tokens, 180)
        self.assertEqual(res.output_tokens, 55)
        self.assertEqual(res.total_tokens, 235)
        self.assertGreaterEqual(res.latency_ms, 0.0)

        # Test schema validator rejects invalid enum or missing field
        invalid_data = dict(VALID_CLAIM_JSON)
        invalid_data["claim_type"] = "unsupported_claim_type"
        errs = validate_claimfast_output(invalid_data)
        self.assertTrue(any("Invalid claim_type" in e for e in errs))

    def test_11_evaluation_runner_skips_completed_jobs_on_resume(self):
        """Scenario 11: Evaluation runner detects existing job IDs and skips completed jobs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            out_file = tmp_path / "evaluation_results.jsonl"
            prompt_dir = tmp_path / "prompts"
            prompt_dir.mkdir()

            # Create dummy prompt templates
            for s in ["zero_shot", "few_shot_k3", "few_shot_k5", "few_shot_k8", "structured_reasoning"]:
                (prompt_dir / f"{s}.txt").write_text("Prompt for {{message}}", encoding="utf-8")

            # Create dummy test dataset with 2 records
            test_file = tmp_path / "test.jsonl"
            with open(test_file, "w", encoding="utf-8") as tf:
                tf.write(json.dumps({"id": "TEST001", "message": "Message 1"}) + "\n")
                tf.write(json.dumps({"id": "TEST002", "message": "Message 2"}) + "\n")

            # Pre-populate output file with 2 already completed jobs
            pre_completed_1 = {
                "job_id": "zero_shot_TEST001_run1",
                "record_id": "TEST001",
                "prompt_strategy": "zero_shot",
                "run_number": 1,
                "status": "SUCCESS",
            }
            pre_completed_2 = {
                "job_id": "zero_shot_TEST002_run1",
                "record_id": "TEST002",
                "prompt_strategy": "zero_shot",
                "run_number": 1,
                "status": "SUCCESS",
            }
            with open(out_file, "w", encoding="utf-8") as out_f:
                out_f.write(json.dumps(pre_completed_1) + "\n")
                out_f.write(json.dumps(pre_completed_2) + "\n")

            # Verify completed job parser
            completed = get_completed_job_ids(out_file)
            self.assertEqual(completed, {"zero_shot_TEST001_run1", "zero_shot_TEST002_run1"})

            # Create mock client for runner
            mock_client = MagicMock()
            mock_client.config.model = "llama-3.3-70b-versatile"
            mock_client.generate.return_value = GenerationResult(
                success=True,
                raw_response=json.dumps(VALID_CLAIM_JSON),
                parsed_json=VALID_CLAIM_JSON,
                model_name="llama-3.3-70b-versatile",
                credential_alias="key_1",
                status="SUCCESS",
            )

            # Run with only zero_shot strategy and 1 run (total 2 jobs, both already done!)
            runner = EvaluationRunner(
                client=mock_client,
                prompt_dir=prompt_dir,
                test_file=test_file,
                output_file=out_file,
                runs=1,
                strategies=["zero_shot"],
            )

            res = runner.run()
            # Since both jobs were already completed, 0 new jobs executed
            self.assertEqual(res["executed"], 0)
            self.assertEqual(mock_client.generate.call_count, 0)

    def test_12_security_assertion_no_api_key_leakage(self):
        """Scenario 12: Absolute security assertion: raw API key never appears in logs, repr, or outputs."""
        secret_key = "gsk_SuperSecretGroqKey1234567890abcdef"
        config = GroqConfig(keys={"key_1": secret_key})

        # 1. Config representation assertion
        self.assertNotIn(secret_key, repr(config))
        self.assertNotIn(secret_key, str(config))

        # 2. Credential representation assertion
        mgr = GroqKeyManager(config)
        cred = mgr.get_credential("key_1")
        self.assertIsNotNone(cred)
        self.assertNotIn(secret_key, repr(cred))
        self.assertNotIn(secret_key, str(cred))

        # 3. Log scrub assertion
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        logger = logging.getLogger("ClaimFast")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Force sanitize_log on a message containing the secret
        tainted_message = f"Error communicating with upstream host using credential: {secret_key}"
        sanitized = config.sanitize_log(tainted_message)
        self.assertNotIn(secret_key, sanitized)
        self.assertIn("[REDACTED_key_1]", sanitized)

        # 4. Result serialization assertion
        gen_res = GenerationResult(
            success=False,
            raw_response="",
            status="API_ERROR",
            error_message=sanitized,
            credential_alias="key_1",
        )
        res_json = json.dumps(gen_res.to_dict())
        self.assertNotIn(secret_key, res_json)

        logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()

