from dataclasses import dataclass


@dataclass
class ParsedError:
    signature: str
    severity: str
    summary: str


def extract_error(message: str) -> ParsedError:
    signature = message.split(":")[0] if ":" in message else message[:60]
    severity = "high" if "Exception" in message or "ERROR" in message else "medium"
    return ParsedError(signature=signature.strip(), severity=severity, summary=message[:200])
