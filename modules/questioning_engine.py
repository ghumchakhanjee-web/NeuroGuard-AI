"""
Adaptive AI Cross-Questioning Engine
-------------------------------------
This is NOT a fixed/generic question list. Every question shown to the
patient is chosen at runtime based on:
    - which symptoms/body region the patient already reported
    - which hypotheses (possible condition categories) are currently
      competing for the "lead" position
    - which unanswered question would best separate those competing
      hypotheses (a simple discriminative-power heuristic)

Two patients with different symptoms/history will get a DIFFERENT set of
questions, in a DIFFERENT order, and the questioning can change direction
mid-session as hypothesis scores shift after each answer.

If an LLM API key is available (see llm_helper.py), the engine can also ask
the model to phrase a fully dynamic next question using the patient's live
profile as context. Without a key, the rule-based engine below runs the
whole flow (works fully offline, so it is safe for a live demo).
"""

from __future__ import annotations
import random

CATEGORIES = ["musculoskeletal", "peripheral_nerve", "neuromuscular", "vascular", "emergency"]

# Each question:
#   id             unique key
#   text           question text shown to patient
#   applicable_regions : list of body regions this question is relevant for, or "any"
#   applicable_symptoms: list of reported symptoms that trigger relevance, or "any"
#   weights        dict(category -> (yes_delta, no_delta))  i.e. how much this
#                  question moves each hypothesis depending on the answer
#   emergency      bool, True if a "yes" here should immediately raise a red flag
QUESTION_BANK = [
    {
        "id": "worsens_with_activity",
        "text": "Kya pain/discomfort chalne-firne ya movement ke saath badhta hai?",
        "applicable_regions": "any",
        "applicable_symptoms": ["pain", "muscle stiffness", "muscle cramps"],
        "weights": {"musculoskeletal": (2, -1), "vascular": (1, 0)},
    },
    {
        "id": "relieved_by_rest",
        "text": "Kya thodi der rest karne se pain kam ho jata hai?",
        "applicable_regions": "any",
        "applicable_symptoms": ["pain", "muscle cramps"],
        "weights": {"musculoskeletal": (1, 0), "vascular": (2, -1)},
    },
    {
        "id": "numbness_pattern",
        "text": "Kya numbness ya tingling ek specific line/pattern mein feel hoti hai (jaise poori leg ke ek side mein)?",
        "applicable_regions": "any",
        "applicable_symptoms": ["numbness", "tingling"],
        "weights": {"peripheral_nerve": (3, -1), "musculoskeletal": (-1, 0)},
    },
    {
        "id": "weakness_progressive",
        "text": "Kya weakness dheere dheere pichle kuch hafton mein badh rahi hai?",
        "applicable_regions": "any",
        "applicable_symptoms": ["weakness", "difficulty walking", "fatigue"],
        "weights": {"neuromuscular": (3, -1), "musculoskeletal": (-1, 1)},
    },
    {
        "id": "worsens_with_repetition",
        "text": "Kya weakness din ke aakhir mein ya repeated activity ke baad zyada feel hoti hai?",
        "applicable_regions": "any",
        "applicable_symptoms": ["weakness", "fatigue"],
        "weights": {"neuromuscular": (2, 0)},
    },
    {
        "id": "sudden_onset",
        "text": "Kya symptoms achanak (sudden) shuru hue the, minutes ya ek-do ghante mein?",
        "applicable_regions": "any",
        "applicable_symptoms": "any",
        "weights": {"emergency": (3, -1), "musculoskeletal": (-1, 1)},
    },
    {
        "id": "trauma_history",
        "text": "Kya symptoms shuru hone se pehle koi injury, fall ya accident hua tha?",
        "applicable_regions": "any",
        "applicable_symptoms": "any",
        "weights": {"musculoskeletal": (2, 0), "emergency": (1, 0)},
    },
    {
        "id": "walking_distance_pattern",
        "text": "Kya pain ek fixed walking distance ke baad start hoti hai aur rest karne se predictably kam hoti hai?",
        "applicable_regions": ["left thigh", "right thigh", "left calf", "right calf", "left foot", "right foot"],
        "applicable_symptoms": ["pain", "muscle cramps"],
        "weights": {"vascular": (3, -1)},
    },
    {
        "id": "color_temp_change",
        "text": "Kya affected area ka color ya temperature normal se different feel hota hai (thanda/pale)?",
        "applicable_regions": "any",
        "applicable_symptoms": "any",
        "weights": {"vascular": (2, 0)},
    },
    {
        "id": "balance_problem",
        "text": "Kya walking ke waqt balance bigadta hai ya girne ka risk feel hota hai?",
        "applicable_regions": "any",
        "applicable_symptoms": ["difficulty walking", "weakness", "balance problem"],
        "weights": {"neuromuscular": (2, 0), "peripheral_nerve": (1, 0)},
    },
    {
        "id": "bladder_bowel",
        "text": "Kya aapko bladder ya bowel control mein koi problem hui hai (accidental leakage ya control lose hona)?",
        "applicable_regions": "any",
        "applicable_symptoms": "any",
        "weights": {"emergency": (5, 0)},
        "emergency": True,
    },
    {
        "id": "one_sided_face",
        "text": "Kya face ka ek side droop hua ya baat karne mein achanak dikkat hui?",
        "applicable_regions": "any",
        "applicable_symptoms": "any",
        "weights": {"emergency": (5, 0)},
        "emergency": True,
    },
    {
        "id": "tenderness_local",
        "text": "Kya ek specific point par dabane se pain sharply increase hota hai?",
        "applicable_regions": "any",
        "applicable_symptoms": ["pain"],
        "weights": {"musculoskeletal": (2, 0)},
    },
]


class AdaptiveQuestionEngine:
    def __init__(self, symptoms: list[str], body_region: str, max_questions: int = 7):
        self.symptoms = [s.lower() for s in symptoms]
        self.body_region = (body_region or "").lower()
        self.max_questions = max_questions
        self.scores = {c: 1.0 for c in CATEGORIES}   # start neutral/uncertain
        self.scores["emergency"] = 0.0                 # emergency only rises on real signal
        self.asked_ids: list[str] = []
        self.qa_log: list[dict] = []

    # ---- relevance filter -------------------------------------------------
    def _is_relevant(self, q: dict) -> bool:
        if q["id"] in self.asked_ids:
            return False
        regs = q["applicable_regions"]
        syms = q["applicable_symptoms"]
        region_ok = regs == "any" or any(r in self.body_region for r in regs) or not self.body_region
        symptom_ok = syms == "any" or any(s in self.symptoms for s in syms)
        return region_ok and symptom_ok

    # ---- discriminative power heuristic ------------------------------------
    def _leading_categories(self, top_n=2):
        ranked = sorted(self.scores.items(), key=lambda kv: kv[1], reverse=True)
        return [c for c, _ in ranked[:top_n]]

    def _discrimination_score(self, q: dict, leaders: list[str]) -> float:
        """How much this question's weights differ across the currently
        leading hypotheses -> higher means it will help separate them."""
        touched = [q["weights"].get(c, (0, 0)) for c in leaders]
        if not any(any(w) for w in touched):
            return 0.1  # barely relevant, low priority
        yes_vals = [w[0] for w in touched]
        spread = max(yes_vals) - min(yes_vals) if len(yes_vals) > 1 else yes_vals[0]
        emergency_bonus = 4.0 if q.get("emergency") else 0.0
        return spread + emergency_bonus

    # ---- public API ---------------------------------------------------------
    def next_question(self) -> dict | None:
        if len(self.asked_ids) >= self.max_questions:
            return None
        candidates = [q for q in QUESTION_BANK if self._is_relevant(q)]
        if not candidates:
            return None
        leaders = self._leading_categories()
        scored = [(self._discrimination_score(q, leaders), q) for q in candidates]
        scored.sort(key=lambda t: t[0], reverse=True)
        # small randomness among near-ties so repeated demo runs aren't robotic
        top_score = scored[0][0]
        tied = [q for s, q in scored if abs(s - top_score) < 0.25]
        return random.choice(tied)

    def answer(self, question: dict, answer_yes: bool):
        self.asked_ids.append(question["id"])
        for cat, (yes_d, no_d) in question["weights"].items():
            self.scores[cat] += yes_d if answer_yes else no_d
            self.scores[cat] = max(self.scores[cat], 0.0)
        self.qa_log.append({
            "id": question.get("id"),
            "question": question["text"],
            "answer": "Yes" if answer_yes else "No",
        })

    def should_stop(self) -> bool:
        if len(self.asked_ids) >= self.max_questions:
            return True
        if self.scores["emergency"] >= 5:
            return True
        ranked = sorted(self.scores.values(), reverse=True)
        if len(self.asked_ids) >= 4 and ranked[0] - ranked[1] >= 3:
            return True
        return False

    def current_ranking(self):
        total = sum(self.scores.values()) or 1
        return sorted(
            [(c, round((v / total) * 100, 1)) for c, v in self.scores.items()],
            key=lambda t: t[1], reverse=True,
        )
