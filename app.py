import os
import sys
import uuid

import streamlit as st
from PIL import Image
from streamlit_image_coordinates import streamlit_image_coordinates

sys.path.append(os.path.dirname(__file__))

from modules import database as db
from modules.questioning_engine import AdaptiveQuestionEngine
from modules.risk_engine import build_assessment
from modules.red_flags import screen_red_flags
from modules.body_map import (
    REGIONS, NON_VISUAL_REGIONS, MUSCLES_BY_REGION,
    render_body_image, region_at_point, CANVAS_W,
)
from modules.report_generator import generate_pdf
from modules.llm_helper import llm_available, generate_dynamic_question
from modules.doctor_finder import (
    geocode_location, find_nearby_care, SPECIALTY_OSM_TAGS, google_maps_key_configured,
)

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
LOGO_PATH = os.path.join(ASSETS_DIR, "logo.png")
BANNER_PATH = os.path.join(ASSETS_DIR, "banner.png")

st.set_page_config(
    page_title="NeuroGuard AI",
    page_icon=Image.open(LOGO_PATH) if os.path.exists(LOGO_PATH) else "🧠",
    layout="wide",
)
db.init_db()

CUSTOM_CSS = """
<style>
.stApp {
    background: linear-gradient(180deg, #f4f8fb 0%, #eef3f8 40%, #eaf3f2 100%);
}
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #16213e 0%, #1e3c72 100%);
}
section[data-testid="stSidebar"] * { color: #f0f4fa !important; }
div[data-testid="stMetricValue"] { color: #1e3c72; }
.stButton>button {
    border-radius: 10px;
    border: none;
    font-weight: 600;
}
.stButton>button[kind="primary"] {
    background: linear-gradient(90deg, #1e3c72, #2a9d8f);
    color: white;
}
div[data-testid="stForm"], div[data-testid="stContainer"] {
    border-radius: 12px;
}
h1, h2, h3 { color: #1e3c72; }
</style>
"""


def inject_css():
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

STEPS = [
    "Welcome / Login",
    "Patient Profile",
    "Basic Symptoms",
    "Body Map",
    "AI Cross-Questioning",
    "Medical History",
    "AI Risk Assessment",
    "Guidance & Next Steps",
    "Find a Doctor",
    "Final Report",
    "History Dashboard",
]

SYMPTOM_OPTIONS = [
    "Pain", "Weakness", "Numbness", "Tingling", "Muscle stiffness",
    "Tremor", "Fatigue", "Difficulty walking", "Balance problem", "Muscle cramps",
]

SPECIALTY_MAP = {
    "musculoskeletal": "Orthopedic Specialist / Physiotherapist",
    "peripheral_nerve": "Neurologist",
    "neuromuscular": "Neurologist (Neuromuscular specialist)",
    "vascular": "Vascular Specialist / General Physician",
    "emergency": "Emergency Department - go immediately",
}


def init_state():
    defaults = {
        "step": 0,
        "patient": {},
        "symptoms": {},
        "body_map": {},
        "engine": None,
        "current_q": None,
        "history": {},
        "assessment": None,
        "red_flag": None,
        "session_id": None,
        "report_path": None,
        "clicked_region": None,
        "doc_search_point": None,
        "doc_search_result": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def sidebar_progress():
    with st.sidebar:
        if os.path.exists(LOGO_PATH):
            c1, c2 = st.columns([1, 3])
            c1.image(LOGO_PATH, width=55)
            c2.markdown("### NeuroGuard AI")
        else:
            st.markdown("## 🧠 NeuroGuard AI")
        st.caption("Neuromuscular AI Screening Platform")
        if llm_available():
            st.success("LLM-assisted questioning: ON", icon="✨")
        else:
            st.info("Running on rule-based adaptive engine (offline mode)", icon="⚙️")
        st.divider()
        for i, name in enumerate(STEPS):
            marker = "➡️" if i == st.session_state.step else ("✅" if i < st.session_state.step else "⬜")
            st.markdown(f"{marker} {i+1}. {name}")
        st.divider()
        st.caption("⚠️ This tool provides an AI-generated risk assessment for screening "
                   "purposes only. It does not diagnose disease. Always consult a qualified "
                   "healthcare professional.")


def go_next():
    st.session_state.step += 1
    st.rerun()


def go_to(step_idx):
    st.session_state.step = step_idx
    st.rerun()


# ---------------------------------------------------------------- STEP 0 ---
def page_welcome():
    if os.path.exists(BANNER_PATH):
        st.image(BANNER_PATH, use_container_width=True)
    else:
        st.markdown(
            "<h1 style='text-align:center;color:#1e3c72;'>🧠 NeuroGuard AI</h1>"
            "<p style='text-align:center;font-size:18px;color:#555;'>"
            "Conversational, evidence-informed neuromuscular symptom screening</p>",
            unsafe_allow_html=True,
        )
    st.write("")
    col1, col2, col3 = st.columns(3)
    col1.info("🗺️ **Body-mapped**\n\nPinpoint symptoms by region and muscle group.")
    col2.info("💬 **Adaptive AI questioning**\n\nEach question is chosen live based on your answers - not a fixed script.")
    col3.info("📋 **Risk-aware, not diagnostic**\n\nYou always get possible-conditions + a doctor referral, never a false-certain diagnosis.")

    st.divider()
    st.subheader("Get Started")

    tab1, tab2 = st.tabs(["New Patient - Register", "Returning Patient - Login"])
    with tab1:
        with st.form("register_form"):
            name = st.text_input("Full Name")
            c1, c2 = st.columns(2)
            age = c1.number_input("Age", 1, 120, 30)
            gender = c2.selectbox("Gender", ["Female", "Male", "Other / Prefer not to say"])
            contact = st.text_input("Contact (optional)")
            location = st.text_input("City / Location", value="Bahawalpur")
            emergency_contact = st.text_input("Emergency contact (optional)")
            submitted = st.form_submit_button("Register & Continue", type="primary")
            if submitted:
                if not name:
                    st.error("Please enter a name.")
                else:
                    pid = db.generate_patient_id()
                    patient = {
                        "patient_id": pid, "name": name, "age": age, "gender": gender,
                        "contact": contact, "location": location, "emergency_contact": emergency_contact,
                    }
                    db.save_patient(patient)
                    st.session_state.patient = patient
                    st.success(f"Registered! Your Patient ID: **{pid}**")
                    go_next()

    with tab2:
        pid_input = st.text_input("Enter your Patient ID (e.g. NG-2026-00124)")
        if st.button("Login"):
            existing = db.get_patient(pid_input.strip())
            if existing:
                st.session_state.patient = existing
                st.success(f"Welcome back, {existing['name']}!")
                go_next()
            else:
                st.error("Patient ID not found. Please register as a new patient.")


# ---------------------------------------------------------------- STEP 1 ---
def page_profile():
    p = st.session_state.patient
    st.header("👤 Patient Profile")
    st.markdown(f"""
    | Field | Value |
    |---|---|
    | Patient ID | `{p.get('patient_id')}` |
    | Name | {p.get('name')} |
    | Age | {p.get('age')} |
    | Gender | {p.get('gender')} |
    | Location | {p.get('location')} |
    """)
    st.info("Your Patient ID links all symptoms, history and reports across sessions.")
    if st.button("Continue to Symptoms →", type="primary"):
        go_next()


# ---------------------------------------------------------------- STEP 2 ---
def page_symptoms():
    st.header("📝 Basic Symptoms")
    free_text = st.text_area(
        "Describe your problem in your own words",
        placeholder="e.g. Mujhe left thigh mein pain hai jo walking ke waqt increase hota hai...",
    )
    selected = st.multiselect("Select all symptoms that apply", SYMPTOM_OPTIONS)

    c1, c2 = st.columns(2)
    severity = c1.slider("Pain / discomfort severity", 0, 10, 5)
    duration = c2.selectbox("Duration", ["< 3 days", "3-7 days", "1-2 weeks", "2-4 weeks", "1-3 months", "> 3 months"])
    c3, c4 = st.columns(2)
    frequency = c3.selectbox("Frequency", ["Constant", "Intermittent", "Only with activity", "Occasional"])
    onset = c4.selectbox("Onset", ["Gradual", "Sudden (minutes/hours)"])

    if st.button("Continue to Body Map →", type="primary"):
        if not selected and not free_text:
            st.error("Please describe your symptoms or select at least one option.")
        else:
            st.session_state.symptoms = {
                "free_text": free_text,
                "selected_symptoms": [s.lower() for s in selected],
                "severity": severity,
                "duration": duration,
                "frequency": frequency,
                "onset": onset,
            }
            go_next()


# ---------------------------------------------------------------- STEP 3 ---
def page_body_map():
    st.header("🗺️ Interactive Body Map")
    st.caption("👉 Click directly on the figure where you feel the problem.")

    if "clicked_region" not in st.session_state:
        st.session_state.clicked_region = None

    col1, col2 = st.columns([1.1, 1])
    with col1:
        img = render_body_image(selected_region=st.session_state.clicked_region)
        coords = streamlit_image_coordinates(img, key="body_click", width=CANVAS_W)
        if coords is not None:
            hit = region_at_point(coords["x"], coords["y"])
            if hit and hit != st.session_state.clicked_region:
                st.session_state.clicked_region = hit
                st.rerun()
        if st.session_state.clicked_region:
            st.success(f"Selected: **{st.session_state.clicked_region}**")
        else:
            st.info("Tap anywhere on the figure to mark the affected area.")

    with col2:
        st.markdown("**Or pick manually:**")
        manual_region = st.selectbox(
            "Body region", REGIONS,
            index=REGIONS.index(st.session_state.clicked_region) if st.session_state.clicked_region in REGIONS else 0,
        )
        if manual_region != st.session_state.clicked_region:
            st.session_state.clicked_region = manual_region

        region = st.session_state.clicked_region
        muscle = None
        if region in MUSCLES_BY_REGION:
            muscle = st.radio("Select specific muscle (if known)", MUSCLES_BY_REGION[region])
        side_note = st.text_input("Exact point of pain (optional description)",
                                   placeholder="e.g. outer-middle part of the thigh")

    if st.button("Continue to AI Cross-Questioning →", type="primary"):
        st.session_state.body_map = {"region": region, "muscle": muscle, "point_note": side_note}
        # initialize adaptive engine fresh for this session
        st.session_state.engine = AdaptiveQuestionEngine(
            symptoms=st.session_state.symptoms.get("selected_symptoms", []),
            body_region=region,
        )
        st.session_state.current_q = None
        go_next()


# ---------------------------------------------------------------- STEP 4 ---
def page_cross_questioning():
    st.header("💬 AI Cross-Questioning")
    st.caption("Questions below are chosen live based on YOUR symptoms, region and previous answers "
               "- not a fixed script. Different patients get different questions.")

    engine: AdaptiveQuestionEngine = st.session_state.engine

    # show conversation so far
    for qa in engine.qa_log:
        with st.chat_message("assistant"):
            st.write(qa["question"])
        with st.chat_message("user"):
            st.write(qa["answer"])

    if engine.should_stop():
        st.success("Enough information gathered for an initial risk assessment.")
        with st.expander("🔍 See live hypothesis confidence (for transparency)"):
            for cat, pct in engine.current_ranking():
                st.write(f"**{cat.replace('_',' ').title()}**: {pct}%")
        if st.button("Continue to Medical History →", type="primary"):
            go_next()
        return

    if st.session_state.current_q is None:
        q = engine.next_question()
        if q is None:
            st.session_state.current_q = "STOP"
        else:
            dyn_text = None
            if llm_available():
                profile = {
                    "symptoms": st.session_state.symptoms,
                    "body_map": st.session_state.body_map,
                }
                dyn_text = generate_dynamic_question(
                    q["text"], profile, engine.qa_log, engine._leading_categories()
                )
            if dyn_text:
                q = {**q, "text": dyn_text}
            st.session_state.current_q = q

    if st.session_state.current_q == "STOP":
        st.info("No more relevant questions for this profile.")
        if st.button("Continue to Medical History →", type="primary"):
            go_next()
        return

    q = st.session_state.current_q
    with st.chat_message("assistant"):
        st.write(q["text"])
    c1, c2, c3 = st.columns([1, 1, 3])
    if c1.button("✅ Yes", use_container_width=True):
        engine.answer(q, True)
        st.session_state.current_q = None
        st.rerun()
    if c2.button("❌ No", use_container_width=True):
        engine.answer(q, False)
        st.session_state.current_q = None
        st.rerun()

    with st.expander("🔍 See live hypothesis confidence (for transparency)"):
        for cat, pct in engine.current_ranking():
            st.write(f"**{cat.replace('_',' ').title()}**: {pct}%")


# ---------------------------------------------------------------- STEP 5 ---
def page_history():
    st.header("📚 Medical History")
    with st.form("history_form"):
        previous_conditions = st.text_area("Previous neurological / muscular conditions", placeholder="None / describe")
        medications = st.text_area("Current medications")
        family_history = st.text_area("Family history of neurological/muscular conditions")
        c1, c2 = st.columns(2)
        diabetes = c1.selectbox("Diabetes?", ["No", "Yes - Type 1", "Yes - Type 2", "Not sure"])
        previous_episode = c2.selectbox("Have you experienced this before?", ["No", "Yes - similar episode", "Yes - worse episode"])
        uploaded = st.file_uploader("Upload previous reports (optional): Lab / EMG / Imaging", accept_multiple_files=True)
        submitted = st.form_submit_button("Continue to AI Risk Assessment →", type="primary")
        if submitted:
            st.session_state.history = {
                "previous_conditions": previous_conditions or "None reported",
                "medications": medications or "None reported",
                "family_history": family_history or "None reported",
                "diabetes": diabetes,
                "previous_episode": previous_episode,
                "uploaded_files": [f.name for f in uploaded] if uploaded else [],
            }
            go_next()


# ---------------------------------------------------------------- STEP 6 ---
def page_assessment():
    st.header("🧬 AI Risk Assessment")
    engine: AdaptiveQuestionEngine = st.session_state.engine
    ranking = engine.current_ranking()

    answered = {
        qa.get("id"): (qa.get("answer") == "Yes")
        for qa in engine.qa_log
        if qa.get("id")
    }
    flat = {
        "symptoms": st.session_state.symptoms.get("selected_symptoms", []),
        "sudden_onset": st.session_state.symptoms.get("onset") == "Sudden (minutes/hours)",
        "emergency_score": engine.scores.get("emergency", 0),
        "bladder_bowel": answered.get("bladder_bowel", False),
        "one_sided_face": answered.get("one_sided_face", False),
        "rapid_progression": answered.get("sudden_onset", False),
        "major_trauma": answered.get("trauma_history", False),
    }

    red_flag = screen_red_flags(flat)
    assessment = build_assessment(ranking, red_flag["urgent"])
    st.session_state.assessment = assessment
    st.session_state.red_flag = red_flag

    st.markdown(f"### Overall Risk: {assessment['overall_risk']}")
    st.caption("This is a risk ASSESSMENT for screening purposes - not a confirmed diagnosis.")

    st.subheader("Possible Conditions / Areas Requiring Evaluation")
    for cond in assessment["possible_conditions"]:
        with st.container(border=True):
            st.markdown(f"**{cond['label']}**  \nConfidence: `{cond['confidence_label']}` ({cond['confidence_pct']}%)")
            for ev in cond["evidence"]:
                st.write(f"- {ev}")

    st.subheader("🚨 Urgency / Red-Flag Check")
    if red_flag["urgent"]:
        st.error("**URGENT MEDICAL ATTENTION RECOMMENDED**\n\nYour responses indicate symptoms that should "
                  "be evaluated promptly by a qualified healthcare professional.")
        for r in red_flag["reasons"]:
            st.write(f"- {r}")
    else:
        st.success("🟢 No immediate red flags detected. Routine clinical evaluation may be appropriate.")

    if st.button("Continue to Guidance →", type="primary"):
        go_next()


# ---------------------------------------------------------------- STEP 7 ---
def page_guidance():
    st.header("🧭 Guidance & Next Steps")
    assessment = st.session_state.assessment
    seen = set()
    st.subheader("Your personalized guidance")
    for cond in assessment["possible_conditions"]:
        for g in cond.get("guidance", []):
            if g not in seen:
                st.write(f"✓ {g}")
                seen.add(g)

    st.info("NeuroGuard AI does not prescribe medication. Please discuss any treatment with a licensed physician.")

    top_category = assessment["possible_conditions"][0]["category"] if assessment["possible_conditions"] else "musculoskeletal"
    specialty = SPECIALTY_MAP.get(top_category, "General Physician")
    st.subheader("Recommended specialist")
    st.write(f"**{specialty}**")
    st.session_state["recommended_specialty"] = specialty

    if st.button("Find a Doctor →", type="primary"):
        go_next()
    if st.button("Skip to Final Report"):
        st.session_state.step = STEPS.index("Final Report")
        st.rerun()


# ---------------------------------------------------------------- STEP 8 ---
def page_doctor_finder():
    st.header("🩺 Find a Specialist Near You")
    default_specialty = st.session_state.get("recommended_specialty", "Neurologist")
    specialty_options = list(SPECIALTY_OSM_TAGS.keys())
    specialty = st.selectbox(
        "Specialty needed", specialty_options,
        index=specialty_options.index(default_specialty) if default_specialty in specialty_options else 0,
    )
    location_text = st.text_input(
        "Your location (city, area, or address)",
        value=st.session_state.patient.get("location", "Bahawalpur"),
    )
    radius_km = st.slider("Search radius (km)", 5, 40, 15)
    st.caption("Real, location-based results via OpenStreetMap - no internet on your side means no results, "
               "so make sure the machine running this app is online.")
    if google_maps_key_configured():
        st.caption("ℹ️ A Google Maps key is configured. For the fastest, most reliable results, make sure "
                   "**Geocoding API** and **Places API (New)** are enabled for it in Google Cloud Console. "
                   "Until then the app uses OpenStreetMap.")
    else:
        st.caption("💡 Tip: add a Google Maps key (Geocoding + Places API) in `.streamlit/secrets.toml` for "
                   "faster, more complete results. OpenStreetMap is used automatically otherwise.")

    if st.button("🔍 Search nearby", type="primary"):
        with st.spinner(f"Locating '{location_text}' and searching nearby care..."):
            geo = geocode_location(location_text)
        if not geo:
            st.error("Couldn't find that location. Try a more specific city/area name, or check your internet connection.")
        else:
            lat, lon, display_name = geo
            st.session_state["doc_search_point"] = (lat, lon, display_name)
            with st.spinner("Searching real clinics/hospitals near that point..."):
                result = find_nearby_care(lat, lon, specialty, radius_km=radius_km)
            st.session_state["doc_search_result"] = result

    geo_point = st.session_state.get("doc_search_point")
    result = st.session_state.get("doc_search_result")

    if geo_point:
        st.caption(f"📍 Searching around: {geo_point[2]}")

    if result:
        if result["error"]:
            st.error(result["error"])
        elif not result["results"]:
            st.warning("No clinics/hospitals found in OpenStreetMap data for this radius. Try increasing the search radius.")
        else:
            if result["fallback_used"]:
                st.info(f"No facility specifically tagged for **{specialty}** was found nearby, so "
                        f"showing the closest general clinics/hospitals instead - ask reception for a "
                        f"{specialty} referral on arrival.")
            st.subheader(f"Recommended: go to one of these, sorted by distance")
            for doc in result["results"]:
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 1, 1])
                    c1.markdown(f"**{doc['name']}**  \n{doc['type']}  \n📍 {doc['address']}")
                    c2.metric("Distance", f"{doc['distance_km']} km")
                    c3.link_button("Directions", doc["maps_link"])

    st.divider()
    if st.button("Continue to Final Report →", type="primary"):
        go_next()


# ---------------------------------------------------------------- STEP 9 ---
def page_report():
    st.header("📄 Final Patient Report")
    p = st.session_state.patient
    sym = st.session_state.symptoms
    bm = st.session_state.body_map
    hist = st.session_state.history
    assessment = st.session_state.assessment
    red_flag = st.session_state.red_flag
    engine = st.session_state.engine

    st.markdown(f"""
    ### NeuroGuard AI Assessment Report
    **Patient ID:** `{p.get('patient_id')}`
    **Name:** {p.get('name')}  |  **Age:** {p.get('age')}  |  **Location:** {p.get('location')}

    **Primary Symptoms:** {', '.join(sym.get('selected_symptoms', [])) or '-'}
    **Duration:** {sym.get('duration')}   **Severity:** {sym.get('severity')}/10
    **Affected Region:** {bm.get('region')} {'(' + bm.get('muscle') + ')' if bm.get('muscle') else ''}

    **Overall AI Risk Assessment:** {assessment['overall_risk']}
    """)

    st.subheader("Why did NeuroGuard reach this assessment? (Evidence)")
    st.write("✓ Symptom pattern and severity")
    st.write("✓ Body location and muscle-level detail")
    st.write("✓ Adaptive cross-questioning responses")
    st.write("✓ Medical history")
    st.write("✓ Retrieved medical knowledge base evidence")

    st.subheader("Recommended Next Step")
    if red_flag and red_flag.get("urgent"):
        st.error("Seek prompt medical attention - do not delay evaluation.")
    else:
        st.info("Consult a qualified healthcare professional for clinical examination and appropriate testing.")

    if st.button("📥 Generate PDF Report", type="primary"):
        session_id = str(uuid.uuid4())[:8]
        out_dir = os.path.join(os.path.dirname(__file__), "generated_reports")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"NeuroGuard_Report_{p.get('patient_id')}_{session_id}.pdf")
        generate_pdf(p, sym, bm, engine.qa_log, hist, assessment, red_flag, out_path)
        st.session_state.report_path = out_path
        st.session_state.session_id = session_id

        db.save_session({
            "session_id": session_id,
            "patient_id": p.get("patient_id"),
            "symptoms": sym,
            "body_map": bm,
            "qa_log": engine.qa_log,
            "history": hist,
            "assessment": assessment,
            "red_flag": red_flag,
        })
        st.success("Report generated and saved to your history!")

    if st.session_state.report_path and os.path.exists(st.session_state.report_path):
        with open(st.session_state.report_path, "rb") as f:
            st.download_button("⬇️ Download PDF Report", f, file_name=os.path.basename(st.session_state.report_path))

    if st.button("View History Dashboard →"):
        go_next()


# ---------------------------------------------------------------- STEP 10 --
def page_dashboard():
    st.header("📊 My Health History")
    p = st.session_state.patient
    sessions = db.get_sessions_for_patient(p.get("patient_id"))

    if not sessions:
        st.info("No previous sessions yet.")
    for s in sessions:
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 1, 1])
            region = s["body_map"].get("region", "-")
            c1.markdown(f"**Session:** {region}  \n{s['created_at'][:16].replace('T', ' ')}")
            risk = s["assessment"].get("overall_risk", "-")
            c2.markdown(f"**Risk:** {risk}")
            if c3.button("View", key=f"view_{s['session_id']}"):
                st.json(s["assessment"])

    st.divider()
    if st.button("🔄 Start a New Screening Session"):
        for k in ["symptoms", "body_map", "engine", "current_q", "history", "assessment", "red_flag",
                  "report_path", "session_id", "clicked_region", "doc_search_point", "doc_search_result"]:
            st.session_state[k] = {} if k in ("symptoms", "body_map", "history") else None
        st.session_state.step = STEPS.index("Basic Symptoms")
        st.rerun()


def main():
    init_state()
    inject_css()
    sidebar_progress()
    step_name = STEPS[st.session_state.step]
    pages = {
        "Welcome / Login": page_welcome,
        "Patient Profile": page_profile,
        "Basic Symptoms": page_symptoms,
        "Body Map": page_body_map,
        "AI Cross-Questioning": page_cross_questioning,
        "Medical History": page_history,
        "AI Risk Assessment": page_assessment,
        "Guidance & Next Steps": page_guidance,
        "Find a Doctor": page_doctor_finder,
        "Final Report": page_report,
        "History Dashboard": page_dashboard,
    }
    pages[step_name]()


if __name__ == "__main__":
    main()
