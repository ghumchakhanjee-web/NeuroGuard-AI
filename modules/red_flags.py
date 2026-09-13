"""Red-flag / urgency screening - kept separate from the general risk engine
on purpose, because urgent findings should never be diluted or averaged into
a general risk score."""

RED_FLAG_RULES = [
    {
        "id": "sudden_severe_weakness",
        "check": lambda d: d.get("sudden_onset") is True and "weakness" in d.get("symptoms", []),
        "message": "Sudden onset of weakness reported.",
    },
    {
        "id": "bladder_bowel",
        "check": lambda d: d.get("bladder_bowel") is True,
        "message": "Bladder/bowel control change reported alongside limb symptoms.",
    },
    {
        "id": "facial_speech",
        "check": lambda d: d.get("one_sided_face") is True,
        "message": "One-sided facial drooping or sudden speech difficulty reported.",
    },
    {
        "id": "rapid_progression",
        "check": lambda d: d.get("rapid_progression") is True,
        "message": "Symptoms reported as rapidly worsening (hours, not weeks).",
    },
    {
        "id": "major_trauma",
        "check": lambda d: d.get("major_trauma") is True,
        "message": "Recent major trauma associated with current symptoms.",
    },
    {
        "id": "emergency_score_high",
        "check": lambda d: d.get("emergency_score", 0) >= 5,
        "message": "Overall response pattern strongly matches an urgent-care profile.",
    },
]


def screen_red_flags(flat_data: dict) -> dict:
    triggered = [r["message"] for r in RED_FLAG_RULES if r["check"](flat_data)]
    return {
        "urgent": len(triggered) > 0,
        "reasons": triggered,
    }
