"""
Gemini-native LLM helper (no SDK required — plain requests only).

Reads keys from .streamlit/secrets.toml (preferred) or environment variables.
On every call, tries the cached (model, key) pair first; on failure it rotates
through all candidates and both keys until one succeeds, then caches that
combination so subsequent calls are fast.

Models are tried in priority order.  AQ.-format auth keys MUST use the native
generativelanguage endpoint + x-goog-api-key header (not OpenAI-compatible,
not google-generativeai SDK v1).
"""

from __future__ import annotations
import json
import os
import time
import requests

try:
    import streamlit as st  # noqa: WPS111 — secrets access
except Exception:  # bare-mode / test
    st = None  # type: ignore[assignment]

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODEL_CANDIDATES = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.0-flash"]

SYSTEM_INSTRUCTION = (
    "You are a clinical intake assistant for a screening tool called NeuroGuard AI. "
    "You NEVER give a definitive diagnosis. You only ask ONE short, specific "
    "follow-up question to help narrow down which category of condition is most "
    "likely (musculoskeletal, peripheral nerve, neuromuscular, vascular, or "
    "emergency), based on the patient profile given, or (b) summarize reasoning "
    "in terms of 'possible conditions' and 'risk level', never certainty. "
    "Keep questions short (max 25 words), in the same language style as the "
    "conversation so far (Roman Hindi/Urdu mixed with English is fine)."
)

_REPHRASE_INSTRUCTION = (
    "You are a friendly medical intake assistant. Rephrase the screening "
    "question below into ONE short natural question (max 20 words) that a "
    "patient understands easily.  Keep the exact same medical meaning.  "
    "Use Roman Urdu/Hindi mixed with English.  Return ONLY the rephrased "
    "question — no explanation, no bullet points, no extra text."
)

# ── key helpers ──────────────────────────────────────────────────────────

def _secret(key: str, default: str = "") -> str:
    if st is not None:
        try:
            v = st.secrets.get(key)  # type: ignore[union-attr]
            if v:
                return str(v)
        except Exception:
            pass
    return os.environ.get(key, default)


def _all_keys() -> list[str]:
    primary = _secret("GEMINI_API_KEY")
    backup = _secret("GEMINI_API_KEY_BACKUP")
    keys = []
    if primary:
        keys.append(primary)
    if backup and backup != primary:
        keys.append(backup)
    return keys


def llm_available() -> bool:
    return bool(_all_keys())


# ── request helper ───────────────────────────────────────────────────────

_TIMEOUT = 30

_WORKING: dict[str, str | None] = {"model": None, "key": None}


def _call_gemini(model: str, key: str, prompt: str) -> str | None:
    """Single Gemini REST call.  Returns model text or None on failure."""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 8192,
            "temperature": 0.55,
        },
    }
    try:
        r = requests.post(
            GEMINI_ENDPOINT.format(model=model),
            headers={
                "x-goog-api-key": key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        parts = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [])
        )
        text = "".join(p.get("text", "") for p in parts).strip()
        return text if text else None
    except Exception:
        return None


def _best_available(prompt: str) -> str | None:
    """Try cached combo first, then all (model, key) pairs.  On first success
    cache it so the next call is instant.  Returns empty string | None if
    nothing worked."""
    cached_model = _WORKING["model"]
    cached_key = _WORKING["key"]

    keys = _all_keys()
    ordered: list[tuple[str, str]] = []
    if cached_model and cached_key:
        ordered.append((cached_model, cached_key))
    for m in MODEL_CANDIDATES:
        for k in keys:
            if (m, k) not in ordered:
                ordered.append((m, k))

    for model, key in ordered:
        text = _call_gemini(model, key, prompt)
        if text is not None:
            _WORKING["model"] = model
            _WORKING["key"] = key
            return text
    return None


# ── public API ───────────────────────────────────────────────────────────

def generate_dynamic_question(
    rule_question: str,
    profile: dict,
    qa_log: list[dict],
    leading_hypotheses: list[str],
) -> str | None:
    """Rephrase the rule-based question into a natural patient-friendly
    follow-up using Gemini.  Fallback to None → app shows original rule text.
    """
    if not llm_available():
        return None

    prompt = (
        f"{_REPHRASE_INSTRUCTION}\n\n"
        f"Original question:\n{rule_question}\n\n"
        f"Patient context:\n{json.dumps(profile, default=str)}\n\n"
        f"Already asked:\n{json.dumps(qa_log[-3:], default=str)}\n\n"
        "Rephrase now:"
    )
    return _best_available(prompt)


def generate_dynamic_reasoning(
    profile: dict,
    qa_log: list[dict],
    leading_hypotheses: list[str],
    assessment: dict,
) -> str | None:
    """Optional — generate a short patient-friendly explanation of the
    assessment reasoning.  Fallback to None."""
    if not llm_available():
        return None
    prompt = (
        f"{SYSTEM_INSTRUCTION}\n\n"
        f"Patient profile:\n{profile}\n\n"
        f"Questions/answers:\n{qa_log}\n\n"
        f"Hypotheses: {leading_hypotheses}\n\n"
        f"Current assessment:\n{assessment}\n\n"
        "In 2-3 short sentences, explain in plain language (Roman Urdu/English "
        "mix is fine) why this risk profile was reached and what the patient "
        "should do next.  Keep under 60 words.  Return ONLY the explanation."
    )
    return _best_available(prompt)
