"""
rag_pipeline.py — Dual-source RAG prompt builder for Claude.

Builds a structured prompt that grounds Claude's analysis in two
complementary knowledge sources:

  1. Similar past incidents — errors this workspace has seen before,
     already resolved (root cause + fix known). Retrieved from the
     errors table via pgvector KNN on the error embedding.

  2. Internal runbook sections — the team's own documentation for
     handling known failure classes (OOM procedures, schema migration
     guides, retry strategies, etc.). Retrieved from runbook_chunks
     via the same KNN search.

Both sources are optional — if neither is available (cold start, or
no runbooks ingested yet), the caller falls back to the standard
non-RAG prompt in main.py /analyze.

Prompt structure
----------------
  ## Current error
  <error + pipeline context>

  ## Similar past incidents    (only if available)
  • [ErrorType] Root cause: ... | Fix: ... (similarity=0.92)

  ## Relevant runbook sections  (only if available)
  ### From: spark_oom_runbook.md > "Handling GC Overhead Errors"
  <chunk text>

  Instructions + JSON output spec
"""


def build_debug_prompt(
    error_summary: str,
    similar_incidents: list[str],
    runbook_sections:  list[str] | None = None,
) -> str:
    """
    Build a retrieval-augmented Claude prompt.

    Parameters
    ----------
    error_summary       : Combined error message + pipeline context string.
    similar_incidents   : Formatted strings from errors KNN retrieval.
                          Each string: "[ErrorType] Root cause: ... | Fix: ... (similarity=X.XX)"
    runbook_sections    : Formatted strings from runbook_chunks KNN retrieval.
                          Each string: "From: <file> > <section>\n<chunk_text>"
                          Pass None or [] if no runbooks have been ingested.

    Returns
    -------
    Complete prompt string ready to send to Claude as the user message.
    """
    sections: list[str] = []

    # ── Current error ──────────────────────────────────────────────────────────
    sections.append("## Current error\n" + error_summary)

    # ── Past incidents ─────────────────────────────────────────────────────────
    if similar_incidents:
        incident_block = "\n".join(f"  • {item}" for item in similar_incidents)
        sections.append(
            "## Similar past incidents (retrieved from your workspace history)\n"
            + incident_block
        )

    # ── Runbook sections ───────────────────────────────────────────────────────
    if runbook_sections:
        runbook_block = "\n\n---\n".join(runbook_sections)
        sections.append(
            "## Relevant internal runbook sections (retrieved from your documentation)\n"
            + runbook_block
        )

    # ── Instructions ──────────────────────────────────────────────────────────
    guidance_parts: list[str] = [
        "You are an expert Site Reliability Engineer (SRE).",
    ]

    if similar_incidents:
        guidance_parts.append(
            "Use the past incidents as context. "
            "If their root causes and fixes are relevant, incorporate them. "
            "If they are not relevant, ignore them."
        )

    if runbook_sections:
        guidance_parts.append(
            "Prioritise the runbook sections above all other context — "
            "they represent this team's documented resolution procedures. "
            "Cite the runbook section title when the fix comes from it."
        )

    guidance_parts.append(
        "Provide your analysis as strict JSON with exactly these keys:\n"
        '- "root_cause": A concise explanation of why the error occurred.\n'
        '- "suggested_fix": A specific, actionable command or configuration change.\n'
        '- "confidence_score": A float between 0.0 and 1.0.\n'
        "Do not include any markdown formatting or explanation outside the JSON."
    )

    sections.append("\n".join(guidance_parts))

    return "\n\n".join(sections)
