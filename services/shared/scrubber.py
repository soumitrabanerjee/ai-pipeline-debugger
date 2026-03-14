"""
scrubber.py — PII and secret redaction before logs are stored or sent to LLMs.

Redacts:
  - Email addresses
  - IPv4 addresses
  - Credit card numbers (Visa, MC, Amex, Discover)
  - US phone numbers (formatted)
  - AWS access key IDs and secret access keys
  - Bearer tokens / API keys (key=value patterns)
  - Passwords and secrets (key=value patterns)
  - JWT tokens (three-part base64url)
  - Database connection strings with embedded credentials
  - HTTP(S) URLs with basic-auth credentials
  - PEM private key blocks

Usage:
    from services.shared.scrubber import scrub_text, scrub

    clean = scrub_text(raw_log)                 # returns redacted string
    result = scrub(raw_log)                     # returns ScrubResult with metadata
    if result.was_redacted:
        print(result.redactions)               # list of category names applied
"""

import re
from dataclasses import dataclass, field
from typing import Callable, Union

# ── Replacement tokens ─────────────────────────────────────────────────────────

_R_EMAIL    = "[REDACTED_EMAIL]"
_R_IP       = "[REDACTED_IP]"
_R_CC       = "[REDACTED_CC]"
_R_PHONE    = "[REDACTED_PHONE]"
_R_AWS_KEY  = "[REDACTED_AWS_KEY]"
_R_SECRET   = "[REDACTED_SECRET]"
_R_TOKEN    = "[REDACTED_TOKEN]"
_R_JWT      = "[REDACTED_JWT]"
_R_CONN     = "[REDACTED_CONNECTION_STRING]"
_R_PEM      = "[REDACTED_PEM_KEY]"
_R_PASSWORD = "[REDACTED_PASSWORD]"
_R_URL_CRED = "[REDACTED_URL_CREDENTIALS]"


# ── Pattern registry ───────────────────────────────────────────────────────────

# Each entry: (name, compiled_pattern, replacement)
# replacement can be a str or a callable(match) -> str.
# Order matters: more specific patterns must come before broader ones.

_PatternEntry = tuple[str, re.Pattern, Union[str, Callable]]

_PATTERNS: list[_PatternEntry] = [
    # 1. PEM private key blocks (multi-line; must precede other patterns)
    (
        "pem_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
            r".*?"
            r"-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
            re.DOTALL | re.IGNORECASE,
        ),
        _R_PEM,
    ),

    # 2. JWT tokens (header.payload.signature — all base64url)
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
        _R_JWT,
    ),

    # 3. Database connection strings with embedded user:password
    #    e.g. postgresql://user:s3cr3t@host:5432/db
    (
        "db_connection_string",
        re.compile(
            r'(?:postgresql|postgres|mysql|mongodb(?:\+srv)?|redis|mssql|oracle'
            r'|jdbc:[a-zA-Z]+)://[^:@\s"\']+:[^@\s"\']+@[^\s"\']*',
            re.IGNORECASE,
        ),
        _R_CONN,
    ),

    # 4. HTTP/HTTPS URLs with basic-auth credentials
    #    e.g. https://user:pass@internal.host/api
    (
        "url_credentials",
        re.compile(r'https?://[^:@\s/]+:[^@\s]+@', re.IGNORECASE),
        _R_URL_CRED + "@",
    ),

    # 5. AWS access key IDs  (AKIA / AIPA / ASIA / AROA prefix + 16 uppercase alnum)
    (
        "aws_access_key",
        re.compile(r'\b(AKIA|AIPA|ASIA|AROA)[A-Z0-9]{16}\b'),
        _R_AWS_KEY,
    ),

    # 6. AWS secret access key (key=value pair)
    (
        "aws_secret_key",
        re.compile(
            r'(?P<k>aws_secret_access_key|AWS_SECRET_ACCESS_KEY)\s*[=:]\s*'
            r'["\']?[A-Za-z0-9/+]{40}["\']?',
            re.IGNORECASE,
        ),
        lambda m: f"{m.group('k')}={_R_SECRET}",
    ),

    # 7. Bearer / Authorization / API-key header values and assignment patterns
    #    Matches: Bearer eyXxx, Authorization: Token abc123, api_key=abc123
    (
        "bearer_token",
        re.compile(
            r'(?P<k>Bearer|Authorization|api[_-]?key|apikey|access[_-]?token'
            r'|auth[_-]?token|x-api-key)\s*[=:\s]+["\']?[A-Za-z0-9\-_./+]{20,}["\']?',
            re.IGNORECASE,
        ),
        lambda m: f"{m.group('k')} {_R_TOKEN}",
    ),

    # 8. Generic password / secret key=value assignments
    #    e.g. password=MyS3cr3t, SECRET_KEY="abc", passwd: hunter2
    (
        "password_kv",
        re.compile(
            r'(?P<k>password|passwd|pwd|secret[_-]?key?|credentials?)\s*[=:]\s*'
            r'["\']?[^\s"\'&,;\r\n]{4,}["\']?',
            re.IGNORECASE,
        ),
        lambda m: f"{m.group('k')}={_R_PASSWORD}",
    ),

    # 9. Email addresses
    (
        "email",
        re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'),
        _R_EMAIL,
    ),

    # 10. IPv4 addresses
    (
        "ipv4",
        re.compile(
            r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}'
            r'(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b'
        ),
        _R_IP,
    ),

    # 11. Credit card numbers — major card type patterns (no Luhn check possible in regex)
    (
        "credit_card",
        re.compile(
            r'\b(?:'
            r'4[0-9]{12}(?:[0-9]{3})?'                                    # Visa
            r'|(?:5[1-5][0-9]{2}|222[1-9]|22[3-9][0-9]|2[3-6][0-9]{2}'
            r'|27[01][0-9]|2720)[0-9]{12}'                                 # Mastercard
            r'|3[47][0-9]{13}'                                             # Amex
            r'|3(?:0[0-5]|[68][0-9])[0-9]{11}'                            # Diners
            r'|6(?:011|5[0-9]{2})[0-9]{12}'                               # Discover
            r'|(?:2131|1800|35\d{3})\d{11}'                               # JCB
            r')\b'
        ),
        _R_CC,
    ),

    # 12. US-formatted phone numbers
    #    Matches: (123) 456-7890 | 123-456-7890 | 123.456.7890 | +1 800 555 0100
    (
        "phone",
        re.compile(
            r'(?:\+?1[\s.\-])?'
            r'\(?\d{3}\)?[\s.\-]'
            r'\d{3}[\s.\-]\d{4}\b'
        ),
        _R_PHONE,
    ),
]


# ── Public API ─────────────────────────────────────────────────────────────────

@dataclass
class ScrubResult:
    """
    Result of a scrub() call.

    Attributes
    ----------
    text : str
        The redacted text. Identical to input when nothing was found.
    redactions : list[str]
        Names of pattern categories that triggered at least one redaction.
        Empty list means the text was clean.
    """
    text: str
    redactions: list[str] = field(default_factory=list)

    @property
    def was_redacted(self) -> bool:
        """True if any PII or secret was found and replaced."""
        return bool(self.redactions)


def scrub(text: str) -> ScrubResult:
    """
    Scan *text* for PII and secrets and return a ScrubResult.

    Applies all patterns in order; each pattern replaces its matches with
    a fixed token (e.g. [REDACTED_EMAIL]).  The original string is never
    mutated.

    Parameters
    ----------
    text : str
        Raw log message, stack trace, or any string to sanitise.

    Returns
    -------
    ScrubResult
        .text        — redacted string
        .redactions  — list of pattern names that matched
        .was_redacted — True if anything was redacted
    """
    if not text:
        return ScrubResult(text=text)

    result = text
    applied: list[str] = []

    for name, pattern, replacement in _PATTERNS:
        new_result, count = pattern.subn(replacement, result)
        if count:
            applied.append(name)
            result = new_result

    return ScrubResult(text=result, redactions=applied)


def scrub_text(text: str) -> str:
    """
    Convenience wrapper — returns the redacted string directly.

    Use this when you only need the cleaned text and don't care which
    categories were redacted.
    """
    return scrub(text).text
