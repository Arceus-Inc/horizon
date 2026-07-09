"""Tolerant JSON extraction for LLM replies — shared by every horizon engine that parses model output.

Structured outputs (``response_format``) make the reply a clean JSON object, but the fallback path (a
plain prompt) may return fenced or prose-wrapped JSON. ``extract_json`` pulls the outermost JSON value
(object or array) out of either, so the caller can ``json.loads`` it.
"""

from __future__ import annotations


def extract_json(text: str) -> str:
    """Pull the outermost JSON value out of a model reply that may be fenced or wrapped in prose."""
    stripped = text.strip()
    if "```" in stripped:
        for chunk in stripped.split("```"):
            candidate = chunk[4:].strip() if chunk.startswith("json") else chunk.strip()
            if candidate.startswith("{"):
                stripped = candidate
                break
    start, end = stripped.find("{"), stripped.rfind("}")
    # take the outermost JSON value — an object {...} or a bare array [...]
    starts = [i for i in (start, stripped.find("[")) if i != -1]
    ends = [i for i in (end, stripped.rfind("]")) if i != -1]
    if starts and ends:
        start, end = min(starts), max(ends)
        if end > start:
            return stripped[start : end + 1]
    return stripped
