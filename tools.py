"""
Tool functions for the healthcare navigation AI agent.
Each tool queries the database and returns structured data.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import uuid
import json
import requests
from math import asin, cos, radians, sin, sqrt

from sqlalchemy.orm import Session

from models import Patient, Consultation, Medication, Test, FollowUp, MedicalDocument, DocumentType


# ==================== LOCATION / MAP HELPERS ====================

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
GEOCODE_HEADERS = {"User-Agent": "MediFlow-Healthcare-Agent/1.0"}

FACILITY_TAG_MAP = {
    "hospital": '["amenity"="hospital"]',
    "pharmacy": '["amenity"="pharmacy"]',
    "clinic": '["amenity"="clinic"]',
    "doctor": '["amenity"="doctors"]',
    "diagnostic_center": '["healthcare"="laboratory"]',
}


def geocode_address(address: str) -> Dict[str, Any]:
    """
    Convert free-text address into latitude/longitude using Nominatim.
    """
    if not address or not address.strip():
        return {"error": "Empty address"}

    try:
        params = {"q": address, "format": "json", "limit": 1, "addressdetails": 1}
        resp = requests.get(NOMINATIM_URL, params=params, headers=GEOCODE_HEADERS, timeout=10)
        resp.raise_for_status()
        results = resp.json()
        if not results:
            return {"error": f"Could not find a location matching: {address}. Try adding city and country."}

        top = results[0]
        return {
            "latitude": float(top["lat"]),
            "longitude": float(top["lon"]),
            "display_name": top.get("display_name", address),
        }
    except requests.RequestException as e:
        return {"error": f"Geocoding service unavailable: {str(e)}"}
    except (KeyError, ValueError, IndexError, TypeError) as e:
        return {"error": f"Geocoding parse error: {str(e)}"}


def _save_patient_location(patient: Patient, db: Session, latitude: float, longitude: float, display_name: str = None):
    patient.latitude = latitude
    patient.longitude = longitude
    patient.location_updated_at = datetime.utcnow()
    if display_name and not patient.address:
        patient.address = display_name
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


def _get_patient_coordinates(patient: Patient, db: Session):
    if patient.latitude is not None and patient.longitude is not None:
        return {
            "latitude": float(patient.latitude),
            "longitude": float(patient.longitude),
            "display_name": patient.address or f"{patient.latitude},{patient.longitude}",
            "source": "saved_coordinates",
        }

    if patient.address:
        geo = geocode_address(patient.address)
        if geo and not geo.get("error"):
            _save_patient_location(
                patient=patient,
                db=db,
                latitude=geo["latitude"],
                longitude=geo["longitude"],
                display_name=geo.get("display_name"),
            )
            return {
                "latitude": geo["latitude"],
                "longitude": geo["longitude"],
                "display_name": geo.get("display_name"),
                "source": "geocoded_address",
            }

    return None


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    d_lat, d_lon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return round(2 * radius * asin(sqrt(a)), 2)


def _coordinates(element: dict) -> tuple:
    if element.get("type") == "node":
        return element.get("lat"), element.get("lon")
    center = element.get("center") or {}
    return center.get("lat"), center.get("lon")


def _run_overpass_query(query: str) -> Optional[list]:
    try:
        resp = requests.post(OVERPASS_URL, data={"data": query}, headers=GEOCODE_HEADERS, timeout=20)
        resp.raise_for_status()
        return resp.json().get("elements", [])
    except requests.RequestException:
        return None


def _build_query(latitude: float, longitude: float, radius_m: int, facility_type: Optional[str]) -> str:
    if facility_type and facility_type.lower() in FACILITY_TAG_MAP:
        clauses = [f'{FACILITY_TAG_MAP[facility_type.lower()]}(around:{radius_m},{latitude},{longitude});']
    else:
        clauses = [
            f'node["amenity"="hospital"](around:{radius_m},{latitude},{longitude});',
            f'way["amenity"="hospital"](around:{radius_m},{latitude},{longitude});',
            f'node["amenity"="pharmacy"](around:{radius_m},{latitude},{longitude});',
            f'way["amenity"="pharmacy"](around:{radius_m},{latitude},{longitude});',
            f'node["amenity"="clinic"](around:{radius_m},{latitude},{longitude});',
            f'way["amenity"="clinic"](around:{radius_m},{latitude},{longitude});',
            f'node["amenity"="doctors"](around:{radius_m},{latitude},{longitude});',
            f'way["amenity"="doctors"](around:{radius_m},{latitude},{longitude});',
            f'node["healthcare"="laboratory"](around:{radius_m},{latitude},{longitude});',
            f'way["healthcare"="laboratory"](around:{radius_m},{latitude},{longitude});',
        ]
    body = "\n  ".join(clauses)
    return f"""[out:json][timeout:20];
(
  {body}
);
out center tags;"""


def _elements_to_places(elements: list, latitude: float, longitude: float, specialty_wanted: Optional[str]) -> tuple:
    matched, everything = [], []
    for element in elements:
        tags = element.get("tags", {})
        lat, lon = _coordinates(element)
        if lat is None or lon is None:
            continue

        street = " ".join(filter(None, [tags.get("addr:housenumber"), tags.get("addr:street")]))
        address = ", ".join(filter(None, [street, tags.get("addr:city"), tags.get("addr:postcode")]))
        place = {
            "name": tags.get("name") or "Unnamed healthcare facility",
            "type": (tags.get("healthcare") or tags.get("amenity") or "healthcare facility").replace("_", " ").title(),
            "specialty": tags.get("healthcare:speciality") or tags.get("speciality"),
            "address": address or None,
            "phone": tags.get("phone") or tags.get("contact:phone"),
            "website": tags.get("website") or tags.get("contact:website"),
            "distance_km": _distance_km(latitude, longitude, float(lat), float(lon)),
            "latitude": lat,
            "longitude": lon,
            "map_url": f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=17/{lat}/{lon}",
        }
        everything.append(place)

        if specialty_wanted:
            searchable = " ".join(str(tags.get(k, "")) for k in ("name", "healthcare:speciality", "speciality", "description")).casefold()
            if specialty_wanted in searchable:
                matched.append(place)

    matched.sort(key=lambda p: p["distance_km"])
    everything.sort(key=lambda p: p["distance_km"])
    return matched, everything


# ==================== TOOL 1: GET PATIENT TIMELINE ====================

def get_patient_timeline(patient_id: str, db: Session) -> Dict[str, Any]:
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        return {"error": f"Patient {patient_id} not found", "events": []}

    events = []

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
    if not start1 or not start2:
        return False
    end1 = end1 or (datetime.utcnow() + timedelta(days=365))
    end2 = end2 or (datetime.utcnow() + timedelta(days=365))
    return start1 <= end2 and start2 <= end1


def check_medication_conflicts(patient_id: str, db: Session) -> Dict[str, Any]:
    medications = db.query(Medication).filter(
        Medication.patient_id == patient_id
    ).all()

    conflicts = []

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

    for i, med1 in enumerate(medications):
        for med2 in medications[i + 1:]:
            if not med1.name or not med2.name:
                continue
            if med1.name.lower().strip() == med2.name.lower().strip():
                continue
            if not med1.prescribed_by or not med2.prescribed_by:
                continue
            if med1.prescribed_by == med2.prescribed_by:
                continue
            if _date_ranges_overlap(med1.start_date, med1.end_date, med2.start_date, med2.end_date):
                conflicts.append({
                    "type": "overlapping_prescription",
                    "severity": "medium",
                    "message": f"'{med1.name}' (from {med1.prescribed_by}) and '{med2.name}' (from {med2.prescribed_by}) overlap in time — these providers may not be aware of each other's prescriptions",
                    "medicine1": {"name": med1.name, "dosage": med1.dosage, "prescribed_by": med1.prescribed_by},
                    "medicine2": {"name": med2.name, "dosage": med2.dosage, "prescribed_by": med2.prescribed_by},
                })

    known_interactions = {
        ("warfarin", "aspirin"): ("high", "Increased bleeding risk"),
        ("metformin", "contrast dye"): ("medium", "May cause kidney issues"),
        ("lisinopril", "potassium supplements"): ("medium", "High potassium risk"),
    }

    active_meds = [
        m.name.lower().strip()
        for m in medications
        if m.name and (not m.end_date or m.end_date > datetime.utcnow())
    ]

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

def explain_medical_term(term: str, language: str = "english") -> Dict[str, Any]:
    explanations = {
        "hypertension": "High blood pressure - the force of blood against artery walls is too strong",
        "diabetes": "A condition where the body cannot properly control blood sugar levels",
        "arthritis": "Inflammation of the joints causing pain and stiffness",
        "asthma": "A lung condition that makes breathing difficult, especially during allergies or exercise",
        "atrial fibrillation": "Irregular heartbeat that can increase stroke risk",
        "gerd": "Acid reflux - stomach acid flows back into the food pipe causing heartburn",
        "osteoporosis": "Bones become weak and brittle, increasing fracture risk",
        "cholesterol": "A fatty substance in blood; high levels can lead to heart disease",
        "pneumonia": "Lung infection causing inflammation and fluid buildup",
        "anemia": "Low red blood cell count, causing fatigue and weakness",
        "migraine": "A severe, often one-sided headache, sometimes with nausea or light sensitivity",
        "thyroid": "A gland in the neck that controls metabolism; too much or too little hormone causes symptoms",
        "jaundice": "Yellowing of skin/eyes caused by a buildup of bilirubin, often linked to liver issues",
        "dehydration": "The body has lost more fluid than it has taken in",
        "metformin": "A medicine for diabetes that helps lower blood sugar by reducing glucose production",
        "lisinopril": "A blood pressure medicine that helps relax blood vessels",
        "aspirin": "A pain reliever and blood thinner that reduces fever and heart attack risk",
        "amoxicillin": "An antibiotic used to treat bacterial infections",
        "ibuprofen": "A pain reliever and anti-inflammatory for aches and fevers",
        "warfarin": "A blood thinner that prevents clots (requires regular blood tests)",
        "paracetamol": "A common medicine for fever and mild pain relief",
    }

    translations_hi = {
        "hypertension": "हाई ब्लड प्रेशर - रक्त वाहिकाओं पर दबाव सामान्य से ज़्यादा है",
        "diabetes": "मधुमेह - शरीर रक्त शर्करा को ठीक से नियंत्रित नहीं कर पाता",
        "arthritis": "जोड़ों में सूजन जिससे दर्द और अकड़न होती है",
        "asthma": "सांस लेने में तकलीफ करने वाली फेफड़ों की बीमारी",
        "cholesterol": "खून में मौजूद एक चिकनाईयुक्त पदार्थ; ज़्यादा होने पर दिल की बीमारी का खतरा",
        "metformin": "डायबिटीज़ की दवा जो रक्त शर्करा कम करने में मदद करती है",
        "lisinopril": "ब्लड प्रेशर की दवा जो रक्त वाहिकाओं को आराम देती है",
        "aspirin": "दर्द निवारक और खून पतला करने वाली दवा",
        "paracetamol": "बुखार और हल्के दर्द के लिए आम दवा",
    }

    translations_pa = {
        "hypertension": "ਹਾਈ ਬਲੱਡ ਪ੍ਰੈਸ਼ਰ - ਖੂਨ ਦੀਆਂ ਨਾੜੀਆਂ 'ਤੇ ਦਬਾਅ ਆਮ ਨਾਲੋਂ ਵੱਧ ਹੈ",
        "diabetes": "ਸ਼ੂਗਰ - ਸਰੀਰ ਖੂਨ ਵਿੱਚ ਸ਼ੂਗਰ ਨੂੰ ਠੀਕ ਤਰ੍ਹਾਂ ਕੰਟਰੋਲ ਨਹੀਂ ਕਰ ਪਾਉਂਦਾ",
        "metformin": "ਸ਼ੂਗਰ ਦੀ ਦਵਾਈ ਜੋ ਖੂਨ ਵਿੱਚ ਸ਼ੂਗਰ ਘਟਾਉਣ ਵਿੱਚ ਮਦਦ ਕਰਦੀ ਹੈ",
        "aspirin": "ਦਰਦ ਘਟਾਉਣ ਅਤੇ ਖੂਨ ਪਤਲਾ ਕਰਨ ਵਾਲੀ ਦਵਾਈ",
    }

    def to_hinglish(english_text: str, term_name: str) -> str:
        return f"{term_name.title()} matlab: {english_text.lower()}"

    term_lower = term.lower().strip()
    base_explanation = explanations.get(term_lower)
    lang = language.lower()

    if base_explanation is None:
        try:
            from llm import get_llm_client
            llm_client = get_llm_client()
            lang_instruction = {
                "hindi": "in simple Hindi (Devanagari script)",
                "hi": "in simple Hindi (Devanagari script)",
                "punjabi": "in simple Punjabi (Gurmukhi script)",
                "pa": "in simple Punjabi (Gurmukhi script)",
                "hinglish": "in casual Hinglish (Hindi-English mix, Roman script)",
            }.get(lang, "in simple English")

            resp = llm_client.call_with_functions(
                messages=[{
                    "role": "user",
                    "content": f"In one short sentence, explain what '{term}' means in medicine, {lang_instruction}, for a patient with no medical background. Do not diagnose or give dosing advice — just define the term."
                }],
                system_prompt="You are a medical term explainer. Respond with ONLY the one-sentence explanation, nothing else.",
            )
            if resp.get("success") and resp.get("content"):
                explanation = resp["content"].strip()
            else:
                explanation = f"I don't have a specific explanation for '{term}' yet. Please ask your doctor for details."
        except Exception:
            explanation = f"I don't have a specific explanation for '{term}' yet. Please ask your doctor for details."
    else:
        explanation = base_explanation
        if lang in ("hindi", "hi") and term_lower in translations_hi:
            explanation = translations_hi[term_lower]
        elif lang in ("punjabi", "pa") and term_lower in translations_pa:
            explanation = translations_pa[term_lower]
        elif lang == "hinglish":
            explanation = to_hinglish(base_explanation, term_lower)

    return {
        "term": term,
        "language": language,
        "explanation": explanation,
        "source": "healthcare_database",
        "recommendation": "For detailed medical information, consult your healthcare provider."
    }


# ==================== TOOL 5: GET UPCOMING FOLLOWUPS ====================

def get_upcoming_followups(patient_id: str, db: Session, days_ahead: int = 30) -> Dict[str, Any]:
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


# ==================== TOOL 6: UPLOAD & EXTRACT DOCUMENT ====================

def save_document_and_extract(
    patient_id: str,
    file_path: str,
    document_type: str,
    db: Session,
    llm_client=None,
) -> Dict[str, Any]:
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        return {"error": f"Patient {patient_id} not found"}

    try:
        import pytesseract
        from PIL import Image
        raw_text = pytesseract.image_to_string(Image.open(file_path)).strip()
    except Exception as e:
        return {"error": f"OCR failed: {str(e)}"}

    if not raw_text:
        return {"error": "OCR could not read any text from this file. Please upload a clearer image."}

    if llm_client is None:
        from llm import get_llm_client
        llm_client = get_llm_client()

    if document_type == "prescription":
        extraction_prompt = (
            "Extract every medicine from this prescription text as a JSON array. "
            'Each item must have exactly these fields: "medicine_name", "dosage", "frequency", "prescribed_by". '
            "If a field is not present in the text, use null. Respond with ONLY the JSON array, no other text.\n\n"
            f"Prescription text:\n{raw_text}"
        )
    else:
        extraction_prompt = (
            "Summarize this medical report/discharge summary as JSON with exactly these fields: "
            '"summary_text", "key_findings" (a list of short strings), "follow_up_needed" (true/false). '
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
    if raw_content.startswith("```"):
        raw_content = raw_content.strip("`")
        raw_content = raw_content.replace("json", "", 1).strip()

    try:
        structured_data = json.loads(raw_content)
    except json.JSONDecodeError:
        return {"error": "Could not parse extracted data. Please try re-uploading the document.", "raw_extraction": raw_content}

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


# ==================== TOOL 7: NEARBY FACILITIES ====================

def find_nearby_facilities(patient_id: str, facility_type: str, db: Session, radius_meters: int = 5000) -> Dict[str, Any]:
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        return {"error": "Patient not found", "count": 0, "facilities": []}

    coords = _get_patient_coordinates(patient, db)
    if not coords:
        return {
            "error": "No saved location for this patient yet. Please save an address first.",
            "patient_location": None,
            "location_source": None,
            "count": 0,
            "facilities": [],
        }

    facility_type = (facility_type or "hospital").lower().strip()
    if facility_type not in FACILITY_TAG_MAP:
        facility_type = "hospital"

    lat = coords["latitude"]
    lon = coords["longitude"]
    tag_filter = FACILITY_TAG_MAP[facility_type]

    query = f"""
    [out:json];[11]
    (
      node{tag_filter}(around:{radius_meters},{lat},{lon});
      way{tag_filter}(around:{radius_meters},{lat},{lon});
    );
    out center tags;
    """

    try:
        resp = requests.post(OVERPASS_URL, data={"data": query}, headers=GEOCODE_HEADERS, timeout=20)
        resp.raise_for_status()
        elements = resp.json().get("elements", [])
    except requests.RequestException as e:
        return {"error": f"Location search service unavailable right now: {str(e)}", "count": 0, "facilities": []}

    facilities = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue

        el_lat = el.get("lat") or (el.get("center") or {}).get("lat")
        el_lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if el_lat is None or el_lon is None:
            continue

        address_parts = [
            tags.get("addr:housenumber"),
            tags.get("addr:street"),
            tags.get("addr:city"),
            tags.get("addr:postcode"),
        ]
        address = ", ".join([p for p in address_parts if p]) or "Exact address not listed in map data"
        facilities.append({
            "name": name,
            "address": address,
            "latitude": el_lat,
            "longitude": el_lon,
            "phone": tags.get("phone") or tags.get("contact:phone"),
            "maps_link": f"https://www.openstreetmap.org/?mlat={el_lat}&mlon={el_lon}#map=18/{el_lat}/{el_lon}",
        })

    facilities = facilities[:10]
    return {
        "facility_type": facility_type,
        "patient_location": coords["display_name"],
        "location_source": coords["source"],
        "count": len(facilities),
        "facilities": facilities,
    }


def find_nearby_doctors(
    patient_id: str,
    specialty: Optional[str] = None,
    facility_type: Optional[str] = None,
    radius_km: float = 5,
    db: Session = None
) -> Dict[str, Any]:
    if db is None:
        return {"error": "Database session is required", "count": 0, "facilities": []}

    result = find_nearby_facilities(
        patient_id=patient_id,
        facility_type=facility_type or "hospital",
        db=db,
        radius_meters=int(radius_km * 1000),
    )
    if specialty:
        result["specialty_requested"] = specialty
    return result