"""
Tool functions for the healthcare navigation AI agent.
Each tool queries the database and returns structured data.
"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Patient, Consultation, Medication, Test, FollowUp, MedicalDocument, DocumentType
from typing import List, Dict, Any, Optional
import uuid
import json


# ==================== TOOL 1: GET PATIENT TIMELINE ====================

def get_patient_timeline(patient_id: str, db: Session) -> Dict[str, Any]:
    """
    Get all medical events for a patient in chronological order:
    consultations, medications (active/past), tests, follow-ups.

    Args:
        patient_id: Patient ID
        db: Database session

    Returns:
        Dict with timeline events sorted by date
    """
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        return {"error": f"Patient {patient_id} not found", "events": []}

    events = []

    # Consultations
    consultations = db.query(Consultation).filter(
        Consultation.patient_id == patient_id
    ).order_by(Consultation.date.desc()).all()

    for consult in consultations:
        events.append({
            "type": "consultation",
            "date": consult.date.isoformat() if consult.date else None,
            "doctor": consult.doctor_name,
            "department": consult.department,
            "chief_complaint": consult.chief_complaint,
            "diagnosis": consult.diagnosis,
            "treatment_plan": consult.treatment_plan,
        })

    # Medications
    medications = db.query(Medication).filter(
        Medication.patient_id == patient_id
    ).order_by(Medication.start_date.desc()).all()

    for med in medications:
        status = "active"
        if med.end_date and med.end_date < datetime.utcnow():
            status = "ended"

        events.append({
            "type": "medication",
            "name": med.name,
            "dosage": med.dosage,
            "frequency": med.frequency,
            "start_date": med.start_date.isoformat() if med.start_date else None,
            "end_date": med.end_date.isoformat() if med.end_date else None,
            "status": status,
            "indication": med.indication,
        })

    # Tests
    tests = db.query(Test).filter(
        Test.patient_id == patient_id
    ).order_by(Test.ordered_date.desc()).all()

    for test in tests:
        events.append({
            "type": "test",
            "test_name": test.test_name,
            "ordered_date": test.ordered_date.isoformat() if test.ordered_date else None,
            "completed_date": test.completed_date.isoformat() if test.completed_date else None,
            "status": test.result_status,
            "result_value": test.result_value,
            "reference_range": test.reference_range,
        })

    # Follow-ups
    followups = db.query(FollowUp).filter(
        FollowUp.patient_id == patient_id
    ).order_by(FollowUp.due_date.asc()).all()

    for followup in followups:
        events.append({
            "type": "followup",
            "due_date": followup.due_date.isoformat() if followup.due_date else None,
            "action": followup.action,
            "status": followup.status,
            "priority": followup.priority,
        })

    # Sort by date (most recent first)
    events.sort(
        key=lambda x: x.get("date") or x.get("start_date") or x.get("ordered_date") or x.get("due_date") or datetime.min.isoformat(),
        reverse=True
    )

    return {
        "patient_id": patient_id,
        "patient_name": patient.name,
        "total_events": len(events),
        "events": events
    }


# ==================== TOOL 2: CHECK MEDICATION CONFLICTS ====================

def _date_ranges_overlap(start1, end1, start2, end2) -> bool:
    """Safely check whether two date ranges overlap, guarding against None dates."""
    if not start1 or not start2:
        return False
    end1 = end1 or (datetime.utcnow() + timedelta(days=365))
    end2 = end2 or (datetime.utcnow() + timedelta(days=365))
    return start1 <= end2 and start2 <= end1


def check_medication_conflicts(patient_id: str, db: Session) -> Dict[str, Any]:
    """
    Check for medication conflicts:
    - Duplicate prescriptions of the same medicine (overlapping dates)
    - Overlapping prescriptions of DIFFERENT medicines from DIFFERENT providers
      (uncoordinated care — the core "conflicting prescriptions" case)
    - Known drug-drug interactions (simplified)

    Args:
        patient_id: Patient ID
        db: Database session

    Returns:
        Dict with conflict warnings
    """
    medications = db.query(Medication).filter(
        Medication.patient_id == patient_id
    ).all()

    conflicts = []

    # ---- Case A: duplicate medicine name, overlapping dates ----
    med_names: Dict[str, List[Medication]] = {}
    for med in medications:
        if not med.name:
            continue
        key = med.name.lower().strip()
        med_names.setdefault(key, []).append(med)

    for med_name, meds in med_names.items():
        if len(meds) > 1:
            for i, med1 in enumerate(meds):
                for med2 in meds[i + 1:]:
                    if _date_ranges_overlap(med1.start_date, med1.end_date, med2.start_date, med2.end_date):
                        conflicts.append({
                            "type": "duplicate",
                            "severity": "high",
                            "message": f"'{med1.name}' was prescribed twice with overlapping dates"
                                       + (f" by {med1.prescribed_by} and {med2.prescribed_by}"
                                          if med1.prescribed_by and med2.prescribed_by and med1.prescribed_by != med2.prescribed_by
                                          else ""),
                            "medicine1": {"name": med1.name, "dosage": med1.dosage, "prescribed_by": med1.prescribed_by},
                            "medicine2": {"name": med2.name, "dosage": med2.dosage, "prescribed_by": med2.prescribed_by},
                        })

    # ---- Case B: DIFFERENT medicines, overlapping dates, DIFFERENT providers ----
    # This is the general "uncoordinated care" case the problem statement asks for —
    # two different doctors prescribing different medicines during the same window
    # without knowing about each other.
    for i, med1 in enumerate(medications):
        for med2 in medications[i + 1:]:
            if not med1.name or not med2.name:
                continue
            if med1.name.lower().strip() == med2.name.lower().strip():
                continue  # already covered by Case A
            if not med1.prescribed_by or not med2.prescribed_by:
                continue  # can't tell if providers differ
            if med1.prescribed_by == med2.prescribed_by:
                continue  # same doctor coordinating own prescriptions is not a conflict
            if _date_ranges_overlap(med1.start_date, med1.end_date, med2.start_date, med2.end_date):
                conflicts.append({
                    "type": "overlapping_prescription",
                    "severity": "medium",
                    "message": f"'{med1.name}' (from {med1.prescribed_by}) and '{med2.name}' (from {med2.prescribed_by}) "
                               f"overlap in time — these providers may not be aware of each other's prescriptions",
                    "medicine1": {"name": med1.name, "dosage": med1.dosage, "prescribed_by": med1.prescribed_by},
                    "medicine2": {"name": med2.name, "dosage": med2.dosage, "prescribed_by": med2.prescribed_by},
                })

    # ---- Case C: known drug-drug interactions (simplified reference list) ----
    known_interactions = {
        ("warfarin", "aspirin"): ("high", "Increased bleeding risk"),
        ("metformin", "contrast dye"): ("medium", "May cause kidney issues"),
        ("lisinopril", "potassium supplements"): ("medium", "High potassium risk"),
    }

    active_meds = [m.name.lower().strip() for m in medications if m.name and (not m.end_date or m.end_date > datetime.utcnow())]

    for (drug1, drug2), (severity, reason) in known_interactions.items():
        if drug1 in active_meds and drug2 in active_meds:
            conflicts.append({
                "type": "drug_interaction",
                "severity": severity,
                "message": f"{drug1.title()} and {drug2.title()} together: {reason}",
                "medicine1": {"name": drug1},
                "medicine2": {"name": drug2},
            })

    return {
        "patient_id": patient_id,
        "has_conflicts": len(conflicts) > 0,
        "conflict_count": len(conflicts),
        "conflicts": conflicts
    }


# ==================== TOOL 3: RECOMMEND SPECIALIST ====================

def recommend_specialist(symptoms: str) -> Dict[str, Any]:
    """
    Recommend medical departments/specialists based on symptom description.
    Uses simple keyword matching (in production, use ML model).

    Args:
        symptoms: Patient description of symptoms

    Returns:
        Dict with specialist recommendations
    """
    symptoms_lower = symptoms.lower()

    specialist_map = {
        "cardiologist": ["chest pain", "heart", "palpitation", "arrhythmia", "heart attack", "hypertension"],
        "pulmonologist": ["cough", "shortness of breath", "asthma", "pneumonia", "lung", "breathing"],
        "gastroenterologist": ["stomach", "abdominal pain", "diarrhea", "nausea", "constipation", "acid reflux", "gerd"],
        "dermatologist": ["skin", "rash", "itching", "acne", "eczema", "psoriasis"],
        "orthopedist": ["joint pain", "fracture", "arthritis", "back pain", "muscle pain", "sprain"],
        "neurologist": ["headache", "migraine", "dizziness", "seizure", "stroke", "numbness", "weakness"],
        "endocrinologist": ["diabetes", "thyroid", "hormones", "metabolism", "weight gain"],
        "nephrologist": ["kidney", "urinary", "renal", "dialysis", "proteinuria"],
        "rheumatologist": ["rheumatoid", "lupus", "inflammation", "autoimmune", "joint swelling"],
        "psychiatrist": ["depression", "anxiety", "mental", "stress", "panic", "emotional"],
    }

    recommendations = []

    for specialty, keywords in specialist_map.items():
        matches = [kw for kw in keywords if kw in symptoms_lower]
        if matches:
            recommendations.append({
                "specialty": specialty,
                "department": specialty.capitalize(),
                "matched_keywords": matches,
                "confidence": min(len(matches) / len(keywords), 1.0),
            })

    recommendations.sort(key=lambda x: x["confidence"], reverse=True)

    if not recommendations:
        recommendations.append({
            "specialty": "general_practitioner",
            "department": "General Practice",
            "matched_keywords": [],
            "confidence": 0.5,
            "note": "Based on symptoms, start with your general practitioner who can refer you to specialists if needed."
        })

    return {
        "symptom_input": symptoms,
        "recommendation_count": len(recommendations),
        "recommendations": recommendations[:3]
    }


# ==================== TOOL 4: EXPLAIN MEDICAL TERM ====================

# ==================== TOOL 4: EXPLAIN MEDICAL TERM ====================

def explain_medical_term(term: str, language: str = "english", llm_client=None) -> Dict[str, Any]:
    """
    ...docstring same rehne do...
    """
    explanations = {
        # ...jaisa hai waisa hi rehne do...
    }

    translations_hi = {
        # ...jaisa hai waisa hi rehne do...
    }

    term_lower = term.lower().strip()
    explanation = explanations.get(term_lower, None)
    used_llm_fallback = False

    if explanation is None:
        if llm_client is None:
            from llm import get_llm_client
            llm_client = get_llm_client()
        prompt = (
            f"Explain the medical term or medicine '{term}' in one or two short, simple "
            f"sentences for an elderly patient with no medical background. No dosing advice. "
            f"Respond ONLY in {language} language, plain text."
        )
        llm_resp = llm_client.call_with_functions(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="You explain medical terms in extremely simple, patient-friendly language.",
        )
        if llm_resp.get("success") and llm_resp.get("content"):
            explanation = llm_resp["content"].strip()
            used_llm_fallback = True
        else:
            explanation = f"I don't have a specific explanation for '{term}'. Please ask your doctor for details."

    elif language.lower() in ["hindi", "hi"] and term_lower in translations_hi:
        explanation = translations_hi[term_lower]

    elif language.lower() not in ["english", "en"]:
        if llm_client is None:
            from llm import get_llm_client
            llm_client = get_llm_client()
        llm_resp = llm_client.call_with_functions(
            messages=[{"role": "user", "content": f"Translate this into simple, everyday {language}:\n\n{explanation}"}],
            system_prompt="You translate medical explanations into simple everyday language.",
        )
        if llm_resp.get("success") and llm_resp.get("content"):
            explanation = llm_resp["content"].strip()
            used_llm_fallback = True

    return {
        "term": term,
        "language": language,
        "explanation": explanation,
        "source": "llm_translation" if used_llm_fallback else "healthcare_database",
        "recommendation": "For detailed medical information, consult your healthcare provider."
    }

# ==================== TOOL 5: GET UPCOMING FOLLOWUPS ====================

def get_upcoming_followups(patient_id: str, db: Session, days_ahead: int = 30) -> Dict[str, Any]:
    """
    Get pending follow-ups and due dates for the next N days.

    Args:
        patient_id: Patient ID
        db: Database session
        days_ahead: How many days ahead to check (default 30)

    Returns:
        Dict with pending follow-ups
    """
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        return {"error": f"Patient {patient_id} not found", "followups": []}

    now = datetime.utcnow()
    future_date = now + timedelta(days=days_ahead)

    followups = db.query(FollowUp).filter(
        FollowUp.patient_id == patient_id,
        FollowUp.status == "pending",
        FollowUp.due_date >= now,
        FollowUp.due_date <= future_date,
    ).order_by(FollowUp.due_date.asc()).all()

    overdue = db.query(FollowUp).filter(
        FollowUp.patient_id == patient_id,
        FollowUp.status == "pending",
        FollowUp.due_date < now,
    ).order_by(FollowUp.due_date.asc()).all()

    followup_list = []

    for fu in overdue:
        days_overdue = (now - fu.due_date).days
        followup_list.append({
            "id": fu.id,
            "action": fu.action,
            "due_date": fu.due_date.isoformat() if fu.due_date else None,
            "status": "OVERDUE",
            "priority": fu.priority or "high",
            "days_overdue": days_overdue,
            "urgency": "HIGH"
        })

    for fu in followups:
        days_until = (fu.due_date - now).days
        followup_list.append({
            "id": fu.id,
            "action": fu.action,
            "due_date": fu.due_date.isoformat() if fu.due_date else None,
            "status": "pending",
            "priority": fu.priority or "medium",
            "days_until": days_until,
            "urgency": "HIGH" if days_until <= 3 else "MEDIUM" if days_until <= 7 else "LOW"
        })

    return {
        "patient_id": patient_id,
        "patient_name": patient.name,
        "total_pending": len(followup_list),
        "overdue_count": len(overdue),
        "upcoming_count": len(followups),
        "followups": followup_list,
        "period_days": days_ahead
    }


# ==================== TOOL 6: UPLOAD & EXTRACT DOCUMENT (Module 2 — was missing) ====================

def save_document_and_extract(
    patient_id: str,
    file_path: str,
    document_type: str,
    db: Session,
    llm_client=None,
) -> Dict[str, Any]:
    """
    Save an uploaded medical document, run OCR on it, use the LLM to convert
    the raw OCR text into structured fields, store the document record, and
    (for prescriptions) insert extracted medicines into the Medication table.

    Args:
        patient_id: Patient ID
        file_path: Path to the uploaded file on disk
        document_type: One of "prescription", "report", "discharge_summary"
        db: Database session
        llm_client: Optional LLM client (falls back to get_llm_client() if not passed)

    Returns:
        Dict with the extracted structured data, ready for the patient to confirm
    """
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        return {"error": f"Patient {patient_id} not found"}

    # ---- Step 1: OCR ----
    try:
        import pytesseract
        from PIL import Image
        raw_text = pytesseract.image_to_string(Image.open(file_path)).strip()
    except Exception as e:
        return {"error": f"OCR failed: {str(e)}"}

    if not raw_text:
        return {"error": "OCR could not read any text from this file. Please upload a clearer image."}

    # ---- Step 2: structure the OCR text via LLM ----
    if llm_client is None:
        from llm import get_llm_client
        llm_client = get_llm_client()

    if document_type == "prescription":
        extraction_prompt = (
            "Extract every medicine from this prescription text as a JSON array. "
            'Each item must have exactly these fields: "medicine_name", "dosage", '
            '"frequency", "prescribed_by". If a field is not present in the text, use null. '
            "Respond with ONLY the JSON array, no other text.\n\n"
            f"Prescription text:\n{raw_text}"
        )
    else:
        extraction_prompt = (
            "Summarize this medical report/discharge summary as JSON with exactly these fields: "
            '"summary_text", "key_findings" (a list of short strings), '
            '"follow_up_needed" (true/false). '
            "Respond with ONLY the JSON object, no other text.\n\n"
            f"Document text:\n{raw_text}"
        )

    llm_response = llm_client.call_with_functions(
        messages=[{"role": "user", "content": extraction_prompt}],
        system_prompt="You are a medical document extraction assistant. You only output valid JSON, nothing else.",
    )

    if not llm_response.get("success"):
        return {"error": f"Extraction failed: {llm_response.get('error')}"}

    raw_content = (llm_response.get("content") or "").strip()
    # Strip markdown code fences if the model wrapped its JSON in them
    if raw_content.startswith("```"):
        raw_content = raw_content.strip("`")
        raw_content = raw_content.replace("json", "", 1).strip()

    try:
        structured_data = json.loads(raw_content)
    except json.JSONDecodeError:
        return {"error": "Could not parse extracted data. Please try re-uploading the document.", "raw_extraction": raw_content}

    # ---- Step 3: save the document record ----
    doc = MedicalDocument(
        id=str(uuid.uuid4()),
        patient_id=patient_id,
        file_url=file_path,
        document_type=DocumentType(document_type),
        uploaded_at=datetime.utcnow(),
        ocr_extracted_text=raw_text,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # ---- Step 4: for prescriptions, insert extracted medicines ----
    inserted_medications = []
    if document_type == "prescription" and isinstance(structured_data, list):
        for item in structured_data:
            medicine_name = item.get("medicine_name")
            if not medicine_name:
                continue
            confidence = "low" if not item.get("dosage") or not item.get("frequency") else "high"
            med = Medication(
                id=str(uuid.uuid4()),
                patient_id=patient_id,
                name=medicine_name,
                dosage=item.get("dosage"),
                frequency=item.get("frequency"),
                prescribed_by=item.get("prescribed_by"),
                start_date=datetime.utcnow(),
                source_document_id=doc.id,
            )
            db.add(med)
            inserted_medications.append({
                "name": medicine_name,
                "dosage": item.get("dosage"),
                "frequency": item.get("frequency"),
                "prescribed_by": item.get("prescribed_by"),
                "confidence": confidence,
            })
        db.commit()

    return {
        "document_id": doc.id,
        "document_type": document_type,
        "extracted_data": structured_data,
        "medications_added": inserted_medications,
        "note": "Please review the extracted data below before it's treated as final.",
    }
    # Paste this complete function at the BOTTOM of your existing tools.py.
# Do not replace the rest of tools.py.

def find_nearby_doctors(patient_id: str, specialty: str | None = None,
                        radius_km: float = 5, db=None) -> dict:
    """Find nearby OSM healthcare listings using the patient's saved location."""
    from maps import search_nearby_healthcare
    from models import Patient, SessionLocal

    owns_session = db is None
    if owns_session:
        db = SessionLocal()
    try:
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return {"error": "Patient not found."}
        if patient.latitude is None or patient.longitude is None:
            return {
                "error": "Location not available.",
                "message": "Please save your location first, then I can find nearby doctors and clinics.",
            }
        return search_nearby_healthcare(
            float(patient.latitude), float(patient.longitude),
            specialty=specialty, radius_km=radius_km,
        )
    finally:
        if owns_session:
            db.close()
