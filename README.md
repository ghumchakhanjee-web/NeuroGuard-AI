# 🧠 NeuroGuard AI — Neuromuscular Screening MVP

An AI-assisted screening tool that combines conversational adaptive
cross-questioning, anatomical body-map localization, patient history, and
evidence-informed risk assessment into a single workflow — **not** a
diagnosis tool. Every output is framed as *possible conditions + risk
level* with a doctor referral, never a confirmed diagnosis.

## ⚡ Quick Start

```bash
# 1. Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
streamlit run app.py
```

Open the URL Streamlit prints (usually http://localhost:8501).

## 🧬 Key feature: real adaptive AI cross-questioning

This is the core differentiator, and it is **not** a fixed question list.

See `modules/questioning_engine.py`:

- The engine keeps a live confidence score for 5 hypothesis categories
  (musculoskeletal, peripheral nerve, neuromuscular, vascular, emergency).
- Every reported symptom / body region updates those scores immediately.
- The **next question is chosen dynamically** — the engine picks whichever
  unanswered question best separates the two currently-leading hypotheses
  (a discriminative-power heuristic), not the next item in a script.
- Two patients with different symptoms/history get a different set of
  questions in a different order. The session can even change direction
  mid-way if answers shift which hypotheses are leading.
- **Optional LLM mode**: set `GEMINI_API_KEY` or `ANTHROPIC_API_KEY` as an
  environment variable before running, and the engine will ask the model to
  phrase the next discriminating question live, using the patient's full
  profile as context (`modules/llm_helper.py`). Without a key, the
  rule-based engine runs the entire demo offline — this makes the app
  reliable for a live hackathon demo with no internet dependency.

```bash
# optional, for LLM-assisted questioning
export ANTHROPIC_API_KEY="sk-ant-..."
# or
export GEMINI_API_KEY="..."
streamlit run app.py
```

## 🗂️ Project structure

```
neuroguard_ai/
├── app.py                     # Main Streamlit wizard (all 11 patient-side pages)
├── requirements.txt
├── assets/
│   ├── logo.png               # App icon / sidebar logo
│   └── banner.png             # Welcome-page banner
├── modules/
│   ├── database.py            # SQLite: patients + session history
│   ├── questioning_engine.py  # Adaptive cross-questioning engine (core AI logic)
│   ├── llm_helper.py          # Optional Gemini/Claude hook for dynamic questions
│   ├── risk_engine.py         # Builds "possible conditions" + confidence from evidence
│   ├── red_flags.py           # Urgency / red-flag detection (kept separate on purpose)
│   ├── body_map.py            # Real click-based body diagram (PIL-drawn, hit-tested)
│   ├── doctor_finder.py       # Real location-based clinic/hospital search (OpenStreetMap)
│   └── report_generator.py    # PDF report generation (fpdf2)
└── data/
    └── medical_knowledge.json # Mini evidence base used for "why" explanations
```

## 🖱️ Real clickable body map

`modules/body_map.py` draws a front-view human figure with PIL and stores
the exact pixel bounding box of every region on that same canvas. The app
uses the `streamlit-image-coordinates` package to capture the literal pixel
the patient taps, then maps it to a region (`region_at_point`). This is a
real click-to-select interaction, not a dropdown styled to look like one —
a manual dropdown is still offered next to it as an accessibility fallback,
and both stay in sync.

## 📍 Real, location-based doctor finder

`modules/doctor_finder.py` does NOT use any mock/hardcoded doctor list. It:

1. Geocodes whatever location text the patient enters (city, area, address)
   using the free **OpenStreetMap Nominatim** API.
2. Searches real clinics/hospitals/doctors around that point using the free
   **Overpass API**, first trying to match the recommended specialty via
   OSM's `healthcare:speciality` tag, and falling back to the nearest
   general clinics/hospitals if nothing specialty-tagged is nearby.
3. Sorts everything by actual straight-line distance and gives each result
   a one-tap **Google Maps directions** link — so the recommendation is a
   real, go-here suggestion tied to the patient's real location, not a
   placeholder.

No paid API key is needed. This does need the machine running the app to
have internet access at that moment (this sandbox environment does not, so
it could only be written and syntax-checked here, not executed live —
it will work as soon as you run it on your own machine or a hosted server).

## 🩺 Workflow implemented (MVP "must-have" scope)

1. Patient registration / login (auto-generated Patient ID)
2. Basic symptoms (free text + structured fields)
3. Interactive body map (region + muscle selection)
4. AI adaptive cross-questioning
5. Medical history (+ optional report upload)
6. AI risk assessment (possible conditions, confidence, evidence)
7. Red-flag / urgency check
8. Guidance & next steps (no prescriptions, ever)
9. Doctor finder (demo data — swap in a real directory/API for production)
10. Final PDF report (downloadable)
11. Patient history dashboard (across sessions, via Patient ID)

## ⚠️ Responsible-AI framing

- The page is called **"AI Risk Assessment"**, never "Diagnosis".
- Output is always **"Possible Conditions"** with a confidence band
  (Low / Low-Moderate / Moderate / Moderate-High), never a definitive claim.
- Every report ends with an explicit disclaimer and a referral to a licensed
  healthcare professional.
- Red flags are evaluated in a dedicated module (`red_flags.py`) rather than
  being averaged into the general risk score, so urgent signals are never
  diluted.
- Patient IDs generated here are synthetic demo IDs — do not use real CNIC,
  insurance, or other sensitive identifiers in a public demo dataset.

## 🚀 Future roadmap (not in MVP)

- Real doctor directory integration (location-based API)
- Doctor/Admin dashboard for reviewing patient cases
- EMG / wearable device integration (aligns with biomedical engineering angle)
- Longitudinal progress tracking across sessions
- Clinical validation study with licensed practitioners
