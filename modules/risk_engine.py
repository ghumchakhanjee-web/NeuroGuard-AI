import json
import os

_KB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "medical_knowledge.json")
with open(_KB_PATH, "r", encoding="utf-8") as f:
    KNOWLEDGE_BASE = json.load(f)


def confidence_label(pct: float) -> str:
    if pct >= 55:
        return "Moderate-High"
    if pct >= 35:
        return "Moderate"
    if pct >= 15:
        return "Low-Moderate"
    return "Low"


def overall_risk_label(top_pct: float, urgent: bool) -> tuple[str, str]:
    if urgent:
        return "🔴 High / Urgent", "red"
    if top_pct >= 45:
        return "🟠 Moderate", "orange"
    return "🟢 Low", "green"


def build_assessment(ranking: list[tuple[str, float]], urgent: bool, top_k: int = 3) -> dict:
    """ranking: list of (category, pct) sorted descending, from the
    questioning engine's current_ranking(). Returns possible-conditions +
    evidence, explicitly framed as risk assessment, never a diagnosis."""

    possible_conditions = []
    for category, pct in ranking[:top_k]:
        if pct <= 0:
            continue
        kb = KNOWLEDGE_BASE.get(category, {})
        possible_conditions.append({
            "category": category,
            "label": kb.get("label", category.replace("_", " ").title()),
            "confidence_pct": pct,
            "confidence_label": confidence_label(pct),
            "evidence": kb.get("evidence_notes", [])[:2],
            "guidance": kb.get("guidance", []),
        })

    top_pct = ranking[0][1] if ranking else 0
    risk_text, risk_color = overall_risk_label(top_pct, urgent)

    return {
        "overall_risk": risk_text,
        "risk_color": risk_color,
        "possible_conditions": possible_conditions,
    }
