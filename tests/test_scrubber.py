"""
Tests for services/shared/scrubber.py — PII and secret redaction.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.shared.scrubber import scrub, scrub_text, ScrubResult


# ── Helpers ────────────────────────────────────────────────────────────────────

def assert_redacted(text: str, token: str, category: str):
    """Assert that *token* appears in the result and *category* was recorded."""
    result = scrub(text)
    assert token in result.text, f"Expected {token!r} in {result.text!r}"
    assert category in result.redactions, (
        f"Expected category {category!r} in {result.redactions}"
    )
    assert result.was_redacted


def assert_clean(text: str):
    """Assert that clean text passes through unmodified."""
    result = scrub(text)
    assert result.text == text, f"Text was unexpectedly modified: {result.text!r}"
    assert not result.was_redacted
    assert result.redactions == []


# ── ScrubResult dataclass ──────────────────────────────────────────────────────

class TestScrubResult:
    def test_was_redacted_true_when_categories_present(self):
        r = ScrubResult(text="clean", redactions=["email"])
        assert r.was_redacted is True

    def test_was_redacted_false_when_empty(self):
        r = ScrubResult(text="clean", redactions=[])
        assert r.was_redacted is False


# ── scrub_text convenience wrapper ────────────────────────────────────────────

class TestScrubTextWrapper:
    def test_returns_string(self):
        assert isinstance(scrub_text("hello world"), str)

    def test_empty_string(self):
        assert scrub_text("") == ""

    def test_clean_text_unchanged(self):
        msg = "Spark executor OOM at stage 5"
        assert scrub_text(msg) == msg


# ── Email addresses ───────────────────────────────────────────────────────────

class TestEmail:
    def test_bare_email(self):
        assert_redacted("Contact admin@example.com for help", "[REDACTED_EMAIL]", "email")

    def test_email_in_stack_trace(self):
        msg = "Failed to notify user.name+tag@subdomain.example.org about job failure"
        result = scrub(msg)
        assert "[REDACTED_EMAIL]" in result.text
        assert "email" in result.redactions

    def test_multiple_emails(self):
        msg = "From a@b.com to c@d.org"
        result = scrub(msg)
        assert result.text.count("[REDACTED_EMAIL]") == 2

    def test_no_false_positive_on_hostname(self):
        # "host.example.com" is not an email
        msg = "Connected to host.example.com:5432"
        result = scrub(msg)
        assert "[REDACTED_EMAIL]" not in result.text


# ── IPv4 addresses ────────────────────────────────────────────────────────────

class TestIPv4:
    def test_public_ip(self):
        assert_redacted("Request from 203.0.113.42 failed", "[REDACTED_IP]", "ipv4")

    def test_private_ip(self):
        assert_redacted("Worker at 10.0.1.25 lost", "[REDACTED_IP]", "ipv4")

    def test_loopback(self):
        assert_redacted("Binding to 127.0.0.1:8080", "[REDACTED_IP]", "ipv4")

    def test_multiple_ips(self):
        msg = "Route from 10.0.0.1 to 10.0.0.2"
        result = scrub(msg)
        assert result.text.count("[REDACTED_IP]") == 2


# ── Credit cards ──────────────────────────────────────────────────────────────

class TestCreditCard:
    def test_visa(self):
        assert_redacted("Card: 4111111111111111", "[REDACTED_CC]", "credit_card")

    def test_mastercard(self):
        assert_redacted("Charged card 5500005555555559", "[REDACTED_CC]", "credit_card")

    def test_amex(self):
        assert_redacted("Amex card 371449635398431", "[REDACTED_CC]", "credit_card")

    def test_discover(self):
        assert_redacted("Discover 6011111111111117", "[REDACTED_CC]", "credit_card")

    def test_no_false_positive_on_short_number(self):
        # A 10-digit number shouldn't match
        assert_clean("Error code 1234567890")


# ── Phone numbers ─────────────────────────────────────────────────────────────

class TestPhone:
    def test_us_dashes(self):
        assert_redacted("Call 800-555-0199 for support", "[REDACTED_PHONE]", "phone")

    def test_us_dots(self):
        assert_redacted("Pager: 415.555.0101", "[REDACTED_PHONE]", "phone")

    def test_us_parentheses(self):
        assert_redacted("Phone (212) 555-1234", "[REDACTED_PHONE]", "phone")

    def test_with_country_code(self):
        assert_redacted("Hotline +1 800 555 0100", "[REDACTED_PHONE]", "phone")


# ── AWS keys ──────────────────────────────────────────────────────────────────

class TestAWSKeys:
    def test_access_key_id(self):
        assert_redacted(
            "Using AWS key AKIAIOSFODNN7EXAMPLE",
            "[REDACTED_AWS_KEY]",
            "aws_access_key",
        )

    def test_secret_access_key_assignment(self):
        msg = "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        result = scrub(msg)
        assert "[REDACTED_SECRET]" in result.text
        assert "aws_secret_key" in result.redactions
        # Key name must be preserved
        assert "aws_secret_access_key" in result.text

    def test_asia_prefix_access_key(self):
        assert_redacted(
            "Assuming role with ASIAQWERTYUIOPASDF12",
            "[REDACTED_AWS_KEY]",
            "aws_access_key",
        )


# ── Passwords / secrets ───────────────────────────────────────────────────────

class TestPasswordKV:
    def test_password_equals(self):
        msg = "password=SuperSecret123"
        result = scrub(msg)
        assert "[REDACTED_PASSWORD]" in result.text
        assert "password" in result.text          # key name preserved
        assert "SuperSecret123" not in result.text

    def test_passwd_colon(self):
        msg = "passwd: hunter2"
        result = scrub(msg)
        assert "[REDACTED_PASSWORD]" in result.text
        assert "hunter2" not in result.text

    def test_secret_key_assignment(self):
        msg = "SECRET_KEY=abc123def456ghi789"
        result = scrub(msg)
        assert "[REDACTED_PASSWORD]" in result.text

    def test_short_value_not_redacted(self):
        # Values shorter than 4 chars are skipped to avoid false positives
        msg = "pwd=ok"
        result = scrub(msg)
        # 'ok' is 2 chars — should not match the {4,} quantifier
        assert "[REDACTED_PASSWORD]" not in result.text


# ── Bearer / API tokens ───────────────────────────────────────────────────────

class TestBearerTokens:
    def test_bearer_header(self):
        msg = "Authorization: Bearer eyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ab"
        result = scrub(msg)
        assert "[REDACTED_TOKEN]" in result.text
        assert "eyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ab" not in result.text

    def test_api_key_assignment(self):
        msg = "api_key=abcdef1234567890abcdef1234"
        result = scrub(msg)
        assert "[REDACTED_TOKEN]" in result.text

    def test_x_api_key(self):
        msg = "x-api-key: sk-live-abcdefghijklmnopqrstuvwx"
        result = scrub(msg)
        assert "[REDACTED_TOKEN]" in result.text


# ── JWT tokens ────────────────────────────────────────────────────────────────

class TestJWT:
    _SAMPLE_JWT = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ"
        ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )

    def test_jwt_redacted(self):
        msg = f"Auth token: {self._SAMPLE_JWT}"
        result = scrub(msg)
        assert "[REDACTED_JWT]" in result.text
        assert self._SAMPLE_JWT not in result.text
        assert "jwt" in result.redactions

    def test_jwt_in_log_line(self):
        msg = f"POST /api/data HTTP/1.1 Authorization: {self._SAMPLE_JWT}"
        result = scrub(msg)
        assert "[REDACTED_JWT]" in result.text


# ── Database connection strings ───────────────────────────────────────────────

class TestDBConnectionStrings:
    def test_postgresql_url(self):
        msg = "Connecting to postgresql://admin:s3cr3tpw@db.internal:5432/mydb"
        result = scrub(msg)
        assert "[REDACTED_CONNECTION_STRING]" in result.text
        assert "s3cr3tpw" not in result.text

    def test_mysql_url(self):
        msg = "DB: mysql://root:password123@10.0.0.5/analytics"
        result = scrub(msg)
        assert "[REDACTED_CONNECTION_STRING]" in result.text

    def test_mongodb_url(self):
        msg = "Store: mongodb://user:pass@cluster.mongodb.net/prod"
        result = scrub(msg)
        assert "[REDACTED_CONNECTION_STRING]" in result.text

    def test_url_without_credentials_not_redacted(self):
        # No user:pass@ — should not match
        msg = "postgresql://db.internal:5432/mydb"
        result = scrub(msg)
        assert "[REDACTED_CONNECTION_STRING]" not in result.text


# ── HTTP URL credentials ──────────────────────────────────────────────────────

class TestURLCredentials:
    def test_http_basic_auth_url(self):
        msg = "Fetching from http://apiuser:mypassword@internal.api.example.com/data"
        result = scrub(msg)
        assert "[REDACTED_URL_CREDENTIALS]" in result.text
        assert "mypassword" not in result.text

    def test_https_basic_auth_url(self):
        msg = "Webhook: https://svc_account:token123@hooks.slack.com/T00/B00/abc"
        result = scrub(msg)
        assert "[REDACTED_URL_CREDENTIALS]" in result.text


# ── PEM private keys ──────────────────────────────────────────────────────────

class TestPEMKeys:
    _PEM = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA2a2rwplBQLzHPZe5TNJT7sGkqFkb3UVE\n"
        "-----END RSA PRIVATE KEY-----"
    )

    def test_rsa_private_key_redacted(self):
        msg = f"Key material:\n{self._PEM}"
        result = scrub(msg)
        assert "[REDACTED_PEM_KEY]" in result.text
        assert "MIIEowIBAAKCAQEA" not in result.text
        assert "pem_key" in result.redactions

    def test_ec_private_key_redacted(self):
        pem = (
            "-----BEGIN EC PRIVATE KEY-----\n"
            "MHQCAQEEIBkg4LKRM/YzGEMJjAZfmMc=\n"
            "-----END EC PRIVATE KEY-----"
        )
        result = scrub(pem)
        assert "[REDACTED_PEM_KEY]" in result.text


# ── Multi-PII in single message ───────────────────────────────────────────────

class TestMultiplePII:
    def test_email_and_ip_together(self):
        msg = "User admin@corp.com connected from 192.168.1.100"
        result = scrub(msg)
        assert "[REDACTED_EMAIL]" in result.text
        assert "[REDACTED_IP]" in result.text
        assert "admin@corp.com" not in result.text
        assert "192.168.1.100" not in result.text
        assert "email" in result.redactions
        assert "ipv4" in result.redactions

    def test_password_and_email_in_error(self):
        msg = "Login failed for user@example.com with password=WrongPass99"
        result = scrub(msg)
        assert "[REDACTED_EMAIL]" in result.text
        assert "[REDACTED_PASSWORD]" in result.text
        assert "WrongPass99" not in result.text

    def test_real_world_pipeline_log_clean(self):
        # A normal stack trace line should not be modified
        msg = (
            "java.lang.OutOfMemoryError: GC overhead limit exceeded\n"
            "\tat org.apache.spark.executor.Executor$TaskRunner.run(Executor.scala:338)"
        )
        result = scrub(msg)
        assert not result.was_redacted
        assert result.text == msg


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_string(self):
        result = scrub("")
        assert result.text == ""
        assert not result.was_redacted

    def test_whitespace_only(self):
        result = scrub("   \n\t  ")
        assert result.text == "   \n\t  "
        assert not result.was_redacted

    def test_none_equivalent_empty(self):
        result = scrub("")
        assert isinstance(result, ScrubResult)

    def test_redactions_list_no_duplicates_per_category(self):
        # Two emails — category should appear only once in redactions
        msg = "a@b.com and c@d.com"
        result = scrub(msg)
        assert result.redactions.count("email") == 1

    def test_original_text_not_mutated(self):
        original = "Contact user@example.com"
        _ = scrub(original)
        assert original == "Contact user@example.com"

    def test_clean_spark_oom_log(self):
        msg = (
            "ExecutorLostFailure (executor 3 exited caused by one of the running tasks) "
            "Reason: Remote RPC client disassociated. Likely due to containers exceeding "
            "thresholds, or network issues. Check driver logs for WARN messages."
        )
        assert_clean(msg)

    def test_clean_airflow_task_log(self):
        msg = (
            "Task exited with return code 1\n"
            "Traceback (most recent call last):\n"
            "  File \"/opt/airflow/dags/etl.py\", line 42, in transform\n"
            "    result = df.groupby('region').agg({'sales': 'sum'})\n"
            "KeyError: 'region'"
        )
        assert_clean(msg)
