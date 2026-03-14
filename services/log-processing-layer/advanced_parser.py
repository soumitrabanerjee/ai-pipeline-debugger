"""
advanced_parser.py — Production-grade deterministic log parsing for Spark and Airflow.

Design principles:
  1. Parse deterministically — no LLM needed to extract structure.
  2. Extract only the signal — filter JVM internals, keep root cause + user frames.
  3. Build compact context — max ~1000 chars so the LLM gets signal, not noise.
  4. Classify exception type precisely — better vector similarity bucketing.

Handles:
  - Spark Java stack traces with nested Caused by: chains
  - PythonException blocks embedded inside Java traces (PySpark UDF failures)
  - Airflow Python tracebacks (Traceback (most recent call last): blocks)
  - OOM / OutOfMemoryError patterns with GC overhead detection
  - Task/Stage/Executor failure context lines
  - Multi-line log blocks (assembles from raw line streams)
"""

import re
from dataclasses import dataclass, field
from typing import Optional


# ── Exception classification ───────────────────────────────────────────────────

# Maps exception class patterns to human-readable categories + severity
_EXCEPTION_CATALOGUE: list[tuple[re.Pattern, str, str]] = [
    # (pattern, category, severity)
    (re.compile(r"OutOfMemoryError|GC overhead limit exceeded|Java heap space"),                      "OOM",              "critical"),
    (re.compile(r"PythonException.*ValueError|ValueError"),                                            "DATA_TYPE",        "high"),
    (re.compile(r"PythonException.*KeyError|KeyError"),                                                "MISSING_KEY",      "high"),
    (re.compile(r"PythonException.*FileNotFoundError|FileNotFoundError"),                              "MISSING_FILE",     "high"),
    (re.compile(r"PythonException.*ConnectionError|ConnectionRefusedError|socket\.timeout"),           "NETWORK",          "high"),
    (re.compile(r"AnalysisException"),                                                                 "SCHEMA_MISMATCH",  "high"),
    (re.compile(r"SparkException.*stage failure|ExecutorLostFailure|FetchFailed"),                    "EXECUTOR_FAILURE",  "high"),
    (re.compile(r"SparkException.*broadcast|MemoryStore"),                                             "BROADCAST_OOM",    "high"),
    (re.compile(r"NullPointerException"),                                                              "NULL_REF",         "medium"),
    (re.compile(r"ClassNotFoundException|NoSuchMethodException|NoSuchFieldException"),                 "CLASSPATH",        "medium"),
    (re.compile(r"IOException|S3Exception|AmazonS3Exception|GCSException"),                           "IO_ERROR",         "medium"),
    (re.compile(r"TimeoutException|TaskKilledException"),                                              "TIMEOUT",          "medium"),
    (re.compile(r"AirflowException|DagRunAlreadyExists|TaskDeferred"),                                "AIRFLOW_INTERNAL",  "low"),
    (re.compile(r"PermissionError|AccessDeniedException|AuthorizationException"),                     "PERMISSIONS",      "high"),
    (re.compile(r"ZeroDivisionError"),                                                                "DIVIDE_BY_ZERO",   "medium"),
    (re.compile(r"AssertionError"),                                                                    "ASSERTION",        "medium"),
    (re.compile(r"UnicodeDecodeError|UnicodeEncodeError"),                                            "ENCODING",         "low"),
]

# JVM / framework internals — frames filtered out of user-visible stack
_INTERNAL_FRAME_PATTERNS = re.compile(
    r"at (org\.apache\.spark|sun\.reflect|java\.lang\.reflect|py4j\.|"
    r"scala\.|akka\.|com\.google\.common|org\.apache\.hadoop\."
    r"|java\.util\.|java\.net\.|java\.io\.|org\.slf4j)",
    re.IGNORECASE,
)

# Spark task context: "Task 0 in stage 19.0 failed 4 times"
_TASK_CONTEXT_RE = re.compile(
    r"Task\s+\d+\s+in\s+stage\s+[\d.]+\s+failed\s+\d+\s+times.*",
    re.IGNORECASE,
)

# Java exception line: "org.apache.spark.SparkException: message"
_JAVA_EXCEPTION_RE = re.compile(
    r"^(?P<cls>[\w.$]+(?:Exception|Error|Failure|Throwable))\s*:\s*(?P<msg>.+)$",
)

# "Caused by: SomeException: message"
_CAUSED_BY_RE = re.compile(
    r"^\s*Caused by:\s*(?P<cls>[\w.$]+)\s*:\s*(?P<msg>.+)$",
)

# Python traceback markers
_PY_TRACEBACK_START = re.compile(r"^\s*Traceback \(most recent call last\):\s*$")
_PY_EXCEPTION_LINE  = re.compile(r"^(?P<cls>[A-Za-z][\w.]*(?:Error|Exception|Warning|Interrupt))\s*:\s*(?P<msg>.+)$")
_PY_EXCEPTION_BARE  = re.compile(r"^(?P<cls>[A-Za-z][\w.]*(?:Error|Exception|Warning|Interrupt))\s*$")
_PY_FILE_FRAME_RE   = re.compile(r'^\s*File "(?P<path>[^"]+)", line (?P<lineno>\d+), in (?P<func>\S+)')

# PythonException wrapper (Spark embedding Python exception)
_PYTHON_EXCEPTION_WRAP_RE = re.compile(
    r"PythonException(?:\(.*?\))?.*?(?P<pyerr>[A-Za-z][\w.]*(?:Error|Exception):[^\n]+)",
    re.DOTALL,
)


# ── Core dataclass ─────────────────────────────────────────────────────────────

@dataclass
class ExceptionBlock:
    """
    Structured representation of a single error event extracted from logs.

    Fields are designed for three purposes:
      - Embedding: exception_class + root_cause_message → vector for similarity search
      - LLM prompt: to_debug_context() → compact, signal-dense string
      - Routing/filtering: severity + category → alert routing, deduplication key
    """
    # Primary exception (outermost in Java / final line in Python)
    exception_class:   str
    exception_message: str

    # Root cause after walking the Caused by: chain
    root_cause_class:   str
    root_cause_message: str

    # All Caused by: entries from outermost → innermost
    causal_chain: list[str] = field(default_factory=list)

    # Non-internal stack frames (user code only)
    user_frames: list[str] = field(default_factory=list)

    # "Task X in stage Y.Z failed N times" if present
    task_context: Optional[str] = None

    # Classification
    severity: str = "medium"   # critical | high | medium | low
    category: str = "UNKNOWN"  # from _EXCEPTION_CATALOGUE

    # Source format for routing
    source_format: str = "unknown"  # spark_java | spark_python | airflow | generic

    # Full raw block (for audit; not sent to LLM)
    raw_block: str = field(default="", repr=False)

    def signature(self) -> str:
        """
        Deduplication key: (category, root_cause_class).
        Two events with the same signature are the same error type.
        """
        return f"{self.category}:{self.root_cause_class}"

    def to_debug_context(self, max_chars: int = 1000) -> str:
        """
        Build a compact, signal-dense string for the LLM prompt.
        Includes task context, exception chain, and user frames.
        Respects max_chars to keep token count predictable.
        """
        parts: list[str] = []

        if self.task_context:
            parts.append(f"Task context: {self.task_context}")

        parts.append(f"Exception: {self.exception_class}: {self.exception_message}")

        if self.causal_chain:
            parts.append("Caused by chain:")
            parts.extend(f"  → {c}" for c in self.causal_chain[-3:])  # last 3 causes

        if self.root_cause_class != self.exception_class:
            parts.append(f"Root cause: {self.root_cause_class}: {self.root_cause_message}")

        if self.user_frames:
            parts.append("User code frames:")
            parts.extend(f"  {f}" for f in self.user_frames[:5])  # top 5 user frames

        result = "\n".join(parts)
        return result[:max_chars]


# ── Block assembler ────────────────────────────────────────────────────────────

class LogBlockAssembler:
    """
    Assembles multi-line log output into discrete error blocks.

    A block starts when an ERROR/EXCEPTION anchor is found and continues
    while lines are part of the same exception (indented, "at ...",
    "Caused by:", Python traceback lines, etc.).
    """

    # Lines that continue an existing error block
    _CONTINUATION_RE = re.compile(
        r"^\s+(at |\.{3}\s*\d+\s+more|Caused by:|Suppressed:|"
        r"File \"|    )"
        r"|^Caused by:"
        r"|^Traceback "
    )

    # Lines that start a new error block
    _ANCHOR_RE = re.compile(
        r"(?:ERROR|EXCEPTION|CRITICAL|FATAL)",
        re.IGNORECASE,
    )

    def assemble(self, raw_log: str) -> list[str]:
        """
        Given a multi-line log string, return a list of error block strings.
        Each string is a self-contained exception block ready for parsing.
        """
        lines = raw_log.splitlines()
        blocks: list[str] = []
        current: list[str] = []

        for line in lines:
            if self._ANCHOR_RE.search(line) and not self._CONTINUATION_RE.match(line):
                if current:
                    blocks.append("\n".join(current))
                current = [line]
            elif current and self._CONTINUATION_RE.match(line):
                current.append(line)
            elif current:
                # Non-continuation, non-anchor: flush current block
                blocks.append("\n".join(current))
                current = []

        if current:
            blocks.append("\n".join(current))

        return [b for b in blocks if b.strip()]


# ── Spark Java parser ──────────────────────────────────────────────────────────

class SparkJavaParser:
    """
    Parses Spark Java/Scala stack traces including:
      - Nested Caused by: chains
      - PythonException wrappers (PySpark UDF failures)
      - Task/Stage failure context lines
      - GC / OOM patterns
    """

    def can_parse(self, block: str) -> bool:
        return bool(
            re.search(r"\bat [\w.$]+\(", block)  # Java stack frame
            or re.search(r"Caused by:", block)
            or re.search(r"PythonException", block)
            or _TASK_CONTEXT_RE.search(block)
        )

    def parse(self, block: str) -> ExceptionBlock:
        lines = block.splitlines()

        task_context = self._extract_task_context(lines)
        exception_class, exception_message = self._extract_top_exception(lines)
        causal_chain, root_cls, root_msg = self._walk_caused_by(lines)
        user_frames = self._extract_user_frames(lines)

        # If PythonException wrapper, try to get inner Python error as root cause
        py_match = _PYTHON_EXCEPTION_WRAP_RE.search(block)
        if py_match and root_cls == exception_class:
            inner = py_match.group("pyerr").strip()
            parts = inner.split(":", 1)
            root_cls = parts[0].strip()
            root_msg = parts[1].strip() if len(parts) > 1 else inner

        severity, category = self._classify(exception_class, root_cls, block)

        return ExceptionBlock(
            exception_class   = exception_class,
            exception_message = exception_message,
            root_cause_class  = root_cls,
            root_cause_message= root_msg,
            causal_chain      = causal_chain,
            user_frames       = user_frames,
            task_context      = task_context,
            severity          = severity,
            category          = category,
            source_format     = "spark_java",
            raw_block         = block,
        )

    # ── internals ──────────────────────────────────────────────────────────────

    def _extract_task_context(self, lines: list[str]) -> Optional[str]:
        for line in lines:
            m = _TASK_CONTEXT_RE.search(line)
            if m:
                return m.group(0).strip()
        return None

    def _extract_top_exception(self, lines: list[str]) -> tuple[str, str]:
        for line in lines:
            m = _JAVA_EXCEPTION_RE.match(line.strip())
            if m:
                return m.group("cls").split(".")[-1], m.group("msg").strip()
        # Fallback: first non-empty line
        first = next((l.strip() for l in lines if l.strip()), "UnknownException: unknown")
        return "UnknownException", first

    def _walk_caused_by(self, lines: list[str]) -> tuple[list[str], str, str]:
        chain: list[str] = []
        root_cls, root_msg = "", ""

        for line in lines:
            m = _CAUSED_BY_RE.match(line)
            if m:
                cls = m.group("cls").split(".")[-1]
                msg = m.group("msg").strip()
                chain.append(f"{cls}: {msg}")
                root_cls, root_msg = cls, msg

        if not root_cls:
            # No Caused by chain — root is the top-level exception
            for line in lines:
                m = _JAVA_EXCEPTION_RE.match(line.strip())
                if m:
                    root_cls = m.group("cls").split(".")[-1]
                    root_msg = m.group("msg").strip()
                    break

        return chain, root_cls or "UnknownException", root_msg or "unknown"

    def _extract_user_frames(self, lines: list[str]) -> list[str]:
        frames: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("at ") and not _INTERNAL_FRAME_PATTERNS.match(stripped):
                # Keep short version: class.method(File.scala:line)
                frames.append(stripped[3:])  # strip "at "
        return frames[:10]  # cap at 10 user frames

    def _classify(self, exc_cls: str, root_cls: str, block: str) -> tuple[str, str]:
        for pattern, category, severity in _EXCEPTION_CATALOGUE:
            if pattern.search(exc_cls) or pattern.search(root_cls) or pattern.search(block):
                return severity, category
        return "medium", "UNKNOWN"


# ── Airflow/Python parser ──────────────────────────────────────────────────────

class AirflowPythonParser:
    """
    Parses Airflow and plain-Python tracebacks:
      - "Traceback (most recent call last):" blocks
      - File/line/function frame extraction (user code only)
      - Final exception class + message line
      - Airflow-specific context (dag_id, task_id from log prefix)
    """

    _AIRFLOW_CTX_RE = re.compile(
        r"\{taskinstance\.py:\d+\}\s+(?:ERROR|CRITICAL)\s+-\s+(?P<msg>.+)"
    )

    def can_parse(self, block: str) -> bool:
        return bool(
            _PY_TRACEBACK_START.search(block)
            or self._AIRFLOW_CTX_RE.search(block)
            or _PY_EXCEPTION_LINE.search(block)
        )

    def parse(self, block: str) -> ExceptionBlock:
        lines = block.splitlines()

        # Extract Airflow task context if present
        task_context: Optional[str] = None
        for line in lines:
            m = self._AIRFLOW_CTX_RE.search(line)
            if m:
                task_context = m.group("msg").strip()[:120]
                break

        exc_cls, exc_msg, user_frames = self._extract_python_traceback(lines)
        severity, category = self._classify(exc_cls, block)

        return ExceptionBlock(
            exception_class    = exc_cls,
            exception_message  = exc_msg,
            root_cause_class   = exc_cls,
            root_cause_message = exc_msg,
            causal_chain       = [],
            user_frames        = user_frames,
            task_context       = task_context,
            severity           = severity,
            category           = category,
            source_format      = "airflow",
            raw_block          = block,
        )

    def _extract_python_traceback(
        self, lines: list[str]
    ) -> tuple[str, str, list[str]]:
        """
        Walk through lines to find the Python traceback block.
        Returns (exception_class, exception_message, user_code_frames).
        """
        in_traceback = False
        user_frames: list[str] = []
        exc_cls = "UnknownException"
        exc_msg = "unknown"

        i = 0
        while i < len(lines):
            line = lines[i]

            if _PY_TRACEBACK_START.match(line):
                in_traceback = True
                i += 1
                continue

            if in_traceback:
                frame_m = _PY_FILE_FRAME_RE.match(line)
                if frame_m:
                    path = frame_m.group("path")
                    # Only keep user code frames — skip site-packages/airflow internals
                    if not re.search(
                        r"site-packages/(airflow|celery|kombu|urllib3|requests|"
                        r"sqlalchemy|aiohttp|pendulum|psycopg2)",
                        path,
                    ):
                        func = frame_m.group("func")
                        lineno = frame_m.group("lineno")
                        # Next line after frame is the code snippet
                        code_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
                        user_frames.append(f"{path}:{lineno} in {func}() → {code_line}")
                    i += 1
                    continue

                # Final exception line
                exc_m = _PY_EXCEPTION_LINE.match(line.strip())
                if exc_m:
                    exc_cls = exc_m.group("cls")
                    exc_msg = exc_m.group("msg").strip()
                    in_traceback = False
                    i += 1
                    continue

                bare_m = _PY_EXCEPTION_BARE.match(line.strip())
                if bare_m:
                    exc_cls = bare_m.group("cls")
                    exc_msg = "no message"
                    in_traceback = False

            i += 1

        return exc_cls, exc_msg, user_frames[:8]

    def _classify(self, exc_cls: str, block: str) -> tuple[str, str]:
        for pattern, category, severity in _EXCEPTION_CATALOGUE:
            if pattern.search(exc_cls) or pattern.search(block):
                return severity, category
        return "medium", "UNKNOWN"


# ── Dispatcher ────────────────────────────────────────────────────────────────

_ASSEMBLER = LogBlockAssembler()
_SPARK_PARSER   = SparkJavaParser()
_AIRFLOW_PARSER = AirflowPythonParser()


def parse_log_block(raw_log: str) -> list[ExceptionBlock]:
    """
    Main entry point.

    Given a raw multi-line log string (from agent.py, webhook, or direct ingest),
    return a list of ExceptionBlock objects — one per distinct error block found.

    Usage:
        blocks = parse_log_block(raw_log_text)
        for block in blocks:
            # Use block.to_debug_context() as LLM prompt context
            # Use block.signature() as deduplication key
            # Use block.severity for alert routing
    """
    raw_blocks = _ASSEMBLER.assemble(raw_log)
    results: list[ExceptionBlock] = []

    for raw in raw_blocks:
        if _SPARK_PARSER.can_parse(raw):
            results.append(_SPARK_PARSER.parse(raw))
        elif _AIRFLOW_PARSER.can_parse(raw):
            results.append(_AIRFLOW_PARSER.parse(raw))
        else:
            # Generic fallback — produce a minimal ExceptionBlock
            first_line = raw.strip().splitlines()[0] if raw.strip() else "unknown"
            results.append(ExceptionBlock(
                exception_class    = "UnknownError",
                exception_message  = first_line[:200],
                root_cause_class   = "UnknownError",
                root_cause_message = first_line[:200],
                source_format      = "generic",
                raw_block          = raw,
            ))

    return results


def parse_single_message(message: str) -> ExceptionBlock:
    """
    Convenience wrapper when you have a single error message string
    (e.g. from the Redis stream fields["message"]).
    Returns the first ExceptionBlock, or a minimal fallback.
    """
    blocks = parse_log_block(message)
    return blocks[0] if blocks else ExceptionBlock(
        exception_class    = message.split(":")[0].strip()[:80] or "UnknownError",
        exception_message  = message[:200],
        root_cause_class   = message.split(":")[0].strip()[:80] or "UnknownError",
        root_cause_message = message[:200],
        source_format      = "generic",
        raw_block          = message,
    )
