def build_debug_prompt(error_summary: str, similar_incidents: list[str]) -> str:
    context = "\n".join(f"- {item}" for item in similar_incidents)
    return (
        "You are an SRE assistant. Analyze the error and suggest actionable fixes.\n"
        f"Error: {error_summary}\n"
        f"Related incidents:\n{context}"
    )
