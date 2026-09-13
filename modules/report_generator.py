import os
from fpdf import FPDF
from fpdf.errors import FPDFException
from datetime import datetime


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_fonts():
    root = _project_root()
    candidates = [
        (os.path.join(root, "assets", "fonts", "Amiri-Regular.ttf"),
         os.path.join(root, "assets", "fonts", "Amiri-Bold.ttf")),
        (os.path.join(root, "assets", "fonts", "amiri", "Amiri-Regular.ttf"),
         os.path.join(root, "assets", "fonts", "amiri", "Amiri-Bold.ttf")),
    ]
    win_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    candidates.append((os.path.join(win_dir, "tahoma.ttf"), os.path.join(win_dir, "tahomabd.ttf")))
    for regular, bold in candidates:
        if regular and os.path.isfile(regular):
            return regular, bold if (bold and os.path.isfile(bold)) else regular
    return None, None


class NeuroGuardReport(FPDF):

    FONT_FAMILY = "NG"

    def setup_fonts(self):
        self._custom_font = False
        regular, bold = _find_fonts()
        if regular:
            try:
                self.add_font(self.FONT_FAMILY, "", regular)
                self.add_font(self.FONT_FAMILY, "B", bold or regular)
                self.add_font(self.FONT_FAMILY, "I", regular)
                self._custom_font = True
            except FPDFException:
                self._custom_font = False
        if not self._custom_font:
            self.FONT_FAMILY = "Helvetica"

    def _clean(self, text):
        if not text:
            return text
        if self._custom_font:
            def ok(o):
                return (
                    o < 0x0300
                    or 0x0370 <= o < 0x0400
                    or 0x0600 <= o <= 0x06FF
                    or 0x0750 <= o <= 0x077F
                    or 0x08A0 <= o <= 0x08FF
                    or 0x2000 <= o < 0x2070
                    or 0x20A0 <= o < 0x20C0
                    or 0xFB50 <= o <= 0xFDFF
                    or 0xFE70 <= o <= 0xFEFF
                )
        else:
            def ok(o):
                return o < 0x80
        return "".join(ch if ok(ord(ch)) else "?" for ch in text)

    def header(self):
        self.set_font(self.FONT_FAMILY, "B", 16)
        self.set_text_color(30, 60, 114)
        self.cell(0, 12, self._clean("NeuroGuard AI - Risk Assessment Report"), ln=True, align="C")
        self.set_font(self.FONT_FAMILY, "I", 9)
        self.set_text_color(120, 120, 120)
        self.cell(0, 6, self._clean("AI-generated screening summary - not a medical diagnosis"), ln=True, align="C")
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font(self.FONT_FAMILY, "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, self._clean(f"Generated {datetime.now().strftime('%d %b %Y, %H:%M')} | Page {self.page_no()}"), align="C")

    def section_title(self, text):
        self.set_font(self.FONT_FAMILY, "B", 12)
        self.set_text_color(30, 60, 114)
        self.ln(3)
        self.cell(0, 8, self._clean(text), ln=True)
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2)

    def body_text(self, text):
        self.set_font(self.FONT_FAMILY, "", 10)
        self.set_text_color(30, 30, 30)
        self.x = self.l_margin
        self.multi_cell(0, 6, self._clean(text))

    def bullet(self, text):
        self.set_font(self.FONT_FAMILY, "", 10)
        self.set_text_color(30, 30, 30)
        self.x = self.l_margin
        self.multi_cell(0, 6, self._clean(f"  -  {text}"))


def _build_pdf(pdf, patient, symptoms, body_map, qa_log, history, assessment, red_flag):
    pdf.section_title("Patient Information")
    pdf.body_text(
        f"Patient ID: {patient.get('patient_id')}\n"
        f"Name: {patient.get('name')}\n"
        f"Age: {patient.get('age')}    Gender: {patient.get('gender')}\n"
        f"Location: {patient.get('location')}"
    )

    pdf.section_title("Reported Symptoms")
    sym_list = symptoms.get("selected_symptoms", [])
    pdf.body_text(", ".join(sym_list) if sym_list else "Not specified")
    if symptoms.get("free_text"):
        pdf.body_text(f"Patient description: \"{symptoms['free_text']}\"")
    pdf.body_text(
        f"Severity: {symptoms.get('severity', '-')}/10   "
        f"Duration: {symptoms.get('duration', '-')}   "
        f"Frequency: {symptoms.get('frequency', '-')}   "
        f"Onset: {symptoms.get('onset', '-')}"
    )

    pdf.section_title("Affected Region")
    pdf.body_text(f"Body region: {body_map.get('region', '-')}\nMuscle (if applicable): {body_map.get('muscle', '-')}")

    if qa_log:
        pdf.section_title("AI Cross-Questioning Summary")
        for qa in qa_log:
            pdf.bullet(f"{qa['question']}  ->  {qa['answer']}")

    if history:
        pdf.section_title("Medical History")
        pdf.body_text(
            f"Previous conditions: {history.get('previous_conditions', '-')}\n"
            f"Current medications: {history.get('medications', '-')}\n"
            f"Family history: {history.get('family_history', '-')}\n"
            f"Previous similar episode: {history.get('previous_episode', '-')}"
        )

    pdf.section_title("AI Risk Assessment")
    pdf.body_text(f"Overall Risk Level: {assessment.get('overall_risk', '-')}")
    for cond in assessment.get("possible_conditions", []):
        pdf.bullet(f"{cond['label']} - Confidence: {cond['confidence_label']} ({cond['confidence_pct']}%)")
        for ev in cond.get("evidence", []):
            pdf.bullet(f"Evidence: {ev}")

    pdf.section_title("Red Flag / Urgency Check")
    if red_flag.get("urgent"):
        pdf.set_text_color(200, 30, 30)
        pdf.body_text("URGENT: Symptom pattern suggests prompt medical evaluation is advisable.")
        pdf.set_text_color(30, 30, 30)
        for reason in red_flag.get("reasons", []):
            pdf.bullet(reason)
    else:
        pdf.body_text("No immediate red flags detected based on responses provided.")

    pdf.section_title("Guidance & Recommended Next Step")
    all_guidance = []
    for cond in assessment.get("possible_conditions", []):
        all_guidance.extend(cond.get("guidance", []))
    seen = set()
    for g in all_guidance:
        if g not in seen:
            pdf.bullet(g)
            seen.add(g)
    pdf.ln(2)
    pdf.set_font(pdf.FONT_FAMILY, "B", 10)
    pdf.x = pdf.l_margin
    pdf.multi_cell(0, 6, "Recommended: Consult a qualified healthcare professional for clinical examination and appropriate testing.")

    pdf.ln(6)
    pdf.set_font(pdf.FONT_FAMILY, "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.x = pdf.l_margin
    pdf.multi_cell(
        0, 5,
        "Disclaimer: NeuroGuard AI is a screening support tool and does not provide a medical "
        "diagnosis. This report reflects an AI-generated risk assessment based on patient-reported "
        "information and should be reviewed by a licensed healthcare professional before any "
        "clinical or treatment decision is made."
    )


def generate_pdf(patient: dict, symptoms: dict, body_map: dict, qa_log: list,
                  history: dict, assessment: dict, red_flag: dict, output_path: str):
    pdf = NeuroGuardReport()
    pdf.setup_fonts()
    pdf.add_page()
    _build_pdf(pdf, patient, symptoms, body_map, qa_log, history, assessment, red_flag)
    pdf.output(output_path)
    return output_path