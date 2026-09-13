import sqlite3
import json
import os
import random
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "neuroguard.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            patient_id TEXT PRIMARY KEY,
            name TEXT,
            age INTEGER,
            gender TEXT,
            contact TEXT,
            location TEXT,
            emergency_contact TEXT,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            patient_id TEXT,
            created_at TEXT,
            symptoms_json TEXT,
            body_map_json TEXT,
            qa_json TEXT,
            history_json TEXT,
            assessment_json TEXT,
            red_flag_json TEXT,
            FOREIGN KEY(patient_id) REFERENCES patients(patient_id)
        )
    """)
    conn.commit()
    conn.close()


def generate_patient_id() -> str:
    year = datetime.now().year
    suffix = random.randint(10000, 99999)
    return f"NG-{year}-{suffix}"


def save_patient(patient: dict):
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO patients
        (patient_id, name, age, gender, contact, location, emergency_contact, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        patient["patient_id"], patient.get("name"), patient.get("age"),
        patient.get("gender"), patient.get("contact"), patient.get("location"),
        patient.get("emergency_contact"), datetime.now().isoformat(),
    ))
    conn.commit()
    conn.close()


def get_patient(patient_id: str):
    conn = get_connection()
    row = conn.execute("SELECT * FROM patients WHERE patient_id=?", (patient_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_session(session: dict):
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO sessions
        (session_id, patient_id, created_at, symptoms_json, body_map_json,
         qa_json, history_json, assessment_json, red_flag_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        session["session_id"], session["patient_id"], datetime.now().isoformat(),
        json.dumps(session.get("symptoms", {})),
        json.dumps(session.get("body_map", {})),
        json.dumps(session.get("qa_log", [])),
        json.dumps(session.get("history", {})),
        json.dumps(session.get("assessment", {})),
        json.dumps(session.get("red_flag", {})),
    ))
    conn.commit()
    conn.close()


def get_sessions_for_patient(patient_id: str):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM sessions WHERE patient_id=? ORDER BY created_at DESC",
        (patient_id,),
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        for key in ("symptoms_json", "body_map_json", "qa_json", "history_json", "assessment_json", "red_flag_json"):
            d[key.replace("_json", "")] = json.loads(d[key])
        result.append(d)
    return result
