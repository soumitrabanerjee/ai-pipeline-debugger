"""
runbook_ingester.py — Markdown runbook → pgvector pipeline.

Converts internal runbook .md files into searchable vector chunks stored
in the runbook_chunks table. Called by the api-layer POST /runbooks/ingest
endpoint during onboarding or whenever runbooks are updated.

Chunking strategy
-----------------
1. Split on markdown headers (##, ###) — each section is a natural semantic unit.
2. If a section exceeds MAX_CHUNK_CHARS, further split on double-newlines (paragraphs).
3. Adjacent chunks share a 50-char overlap so retrieval doesn't miss context at
   section boundaries.
4. Minimum chunk size = 30 chars (skip empty/title-only sections).

The resulting chunks are compact enough to fit in the LLM context window
(~512 tokens each) while retaining enough context for meaningful retrieval.

Usage
-----
    from runbook_ingester import ingest_runbook_text

    chunks = ingest_runbook_text(
        markdown_text = open("spark_oom_runbook.md").read(),
        source_file   = "spark_oom_runbook.md",
        workspace_id  = "42",
    )
    # chunks is list[RunbookChunkRow] ready for DB insert
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


MAX_CHUNK_CHARS = 600   # ~150 tokens; leaves room for error context in prompt
OVERLAP_CHARS   = 50    # shared tail between adjacent chunks

# Markdown header pattern (## or ### only; # is typically document title)
_HEADER_RE = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class RunbookChunkRow:
    """
    One row ready for INSERT into runbook_chunks.

    embedding is populated by the caller (api-layer endpoint) after calling
    the ai-engine /embed endpoint — the ingester itself is embedding-agnostic.
    """
    workspace_id:  str
    source_file:   str
    chunk_index:   int
    section_title: Optional[str]
    chunk_text:    str
    created_at:    str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    embedding:     Optional[list[float]] = None


# ── Chunker ────────────────────────────────────────────────────────────────────

def _split_by_headers(markdown: str) -> list[tuple[Optional[str], str]]:
    """
    Split markdown text into (section_title, section_body) pairs.

    Strategy: find all ## / ### headers, treat everything between two consecutive
    headers as one section. The preamble before the first header gets section_title=None.
    """
    sections: list[tuple[Optional[str], str]] = []

    # Find header positions
    headers = list(_HEADER_RE.finditer(markdown))

    if not headers:
        # No headers — treat entire document as one section
        return [(None, markdown.strip())]

    # Preamble before first header
    preamble = markdown[: headers[0].start()].strip()
    if preamble:
        sections.append((None, preamble))

    for i, header_match in enumerate(headers):
        title = header_match.group(2).strip()
        body_start = header_match.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(markdown)
        body = markdown[body_start:body_end].strip()
        if body:
            sections.append((title, body))

    return sections


def _split_long_section(
    title: Optional[str], body: str, max_chars: int
) -> list[tuple[Optional[str], str]]:
    """
    If a section body exceeds max_chars, split on double-newlines (paragraphs)
    with OVERLAP_CHARS overlap between adjacent chunks.
    """
    if len(body) <= max_chars:
        return [(title, body)]

    paragraphs = re.split(r"\n{2,}", body)
    chunks: list[tuple[Optional[str], str]] = []
    current = ""
    previous_tail = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        candidate = f"{previous_tail}\n\n{para}".strip() if previous_tail else para

        if len(current) + len(para) + 2 <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append((title, current))
            # Carry over the last OVERLAP_CHARS of current as context
            previous_tail = current[-OVERLAP_CHARS:] if len(current) > OVERLAP_CHARS else current
            current = f"{previous_tail}\n\n{para}".strip() if previous_tail else para

    if current:
        chunks.append((title, current))

    return chunks if chunks else [(title, body[:max_chars])]


def ingest_runbook_text(
    markdown_text: str,
    source_file: str,
    workspace_id: str,
    max_chunk_chars: int = MAX_CHUNK_CHARS,
) -> list[RunbookChunkRow]:
    """
    Convert a raw markdown string into a list of RunbookChunkRow objects.

    Parameters
    ----------
    markdown_text   : Raw content of the .md runbook file.
    source_file     : Filename used as identifier in the DB (e.g. "spark_oom.md").
    workspace_id    : Tenant ID — chunks are isolated per workspace.
    max_chunk_chars : Maximum characters per chunk (default: 600).

    Returns
    -------
    List of RunbookChunkRow objects, ready for embedding + DB insert.
    Embedding field is None — caller must fill it via ai-engine /embed.
    """
    # Step 1: split on headers
    sections = _split_by_headers(markdown_text)

    # Step 2: split oversized sections on paragraph boundaries
    all_chunks: list[tuple[Optional[str], str]] = []
    for title, body in sections:
        all_chunks.extend(_split_long_section(title, body, max_chunk_chars))

    # Step 3: filter degenerate chunks, assign indices
    rows: list[RunbookChunkRow] = []
    chunk_index = 0
    now = datetime.now(timezone.utc).isoformat()

    for title, text in all_chunks:
        text = text.strip()
        if len(text) < 30:  # skip empty / title-only sections
            continue

        rows.append(RunbookChunkRow(
            workspace_id  = workspace_id,
            source_file   = source_file,
            chunk_index   = chunk_index,
            section_title = title,
            chunk_text    = text,
            created_at    = now,
        ))
        chunk_index += 1

    return rows
