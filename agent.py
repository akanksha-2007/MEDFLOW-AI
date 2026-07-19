"""Core AI agent: tool calling, persistent chat history, and symptom logging."""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

import tools
from llm import get_llm_client
from models import ChatMessage, Consultation, FollowUp, Medication, Patient, SymptomLog

CONVERSATION_HISTORIES: Dict[str, List[Dict[str, str]]] = {}
MAX_HISTORY_LENGTH = 20
CONFLICT_KEYWORDS = ("conflict", "interact", "clash", "duplicate", "safe together", "safety")
PATIENT_SCOPED_TOOLS = {
    "get_patient_timeline", "check_medication_conflicts",
    "get_upcoming_followups", "find_nearby_doctors",
}

# These only decide whether to retain the patient's *own words* as a symptom log.
# They do not diagnose a condition or assign medical meaning to the message.
HEALTH_PROBLEM_KEYWORDS = (
    "pain", "ache", "fever", "cough", "cold", "headache", "migraine", "dizzy",
    "dizziness", "vomit", "vomiting", "nausea", "diarrhea", "weakness", "fatigue",
    "breath", "breathing", "chest", "rash", "swelling", "bleeding", "infection",
    "diabetes", "hypertension", "asthma", "anxiety", "depression", "symptom",
    "dard", "bukhar", "khansi", "sar dard", "chakkar", "ulti", "kamzori",
    "saans", "sujan", "jalan", "bimari", "problem", "takleef",
)


class HealthcareNavigationAgent:
    SYSTEM_PROMPT = """You are a helpful healthcare navigation assistant for patients.

Help patients understand their records, medication conflicts, follow-ups,
specialist navigation, and nearby healthcare facilities. Do not diagnose,
change medicine doses, or present directory results as emergency care. Use
plain, empathetic language and tell patients to contact a clinician for
medical advice.

Use get_patient_timeline for medical history; check_medication_conflicts for
medicine interaction/safety questions; recommend_specialist for symptoms;
explain_medical_term only for a term or medicine definition;
get_upcoming_followups for future tasks; and find_nearby_doctors for nearby
doctors, clinics, hospitals, or specialists."""

    AUTO_CONFLICT_CHECK_TRIGGERS = {"get_patient_timeline"}

    def __init__(self, db: Session):
        self.db = db
        self.llm = get_llm_client()

    def get_or_create_patient(self, patient_id: str) -> Optional[Patient]:
        return self.db.query(Patient).filter(Patient.id == patient_id).first()

    def get_conversation_history(self, patient_id: str) -> List[Dict[str, str]]:
        """Load saved history once per patient, newest 20 messages in time order."""
        if patient_id not in CONVERSATION_HISTORIES:
            messages = (
                self.db.query(ChatMessage)
                .filter(ChatMessage.patient_id == patient_id)
                .order_by(ChatMessage.created_at.desc())
                .limit(MAX_HISTORY_LENGTH)
                .all()
            )
            messages.reverse()
            CONVERSATION_HISTORIES[patient_id] = [
                {"role": message.role, "content": message.content}
                for message in messages
            ]
        return CONVERSATION_HISTORIES[patient_id]

    def add_to_history(self, patient_id: str, role: str, content: str) -> ChatMessage:
        """Save a real chat message in SQLite and keep a short memory cache."""
        saved_message = ChatMessage(patient_id=patient_id, role=role, content=content)
        self.db.add(saved_message)
        self.db.commit()
        self.db.refresh(saved_message)

        history = self.get_conversation_history(patient_id)
        history.append({"role": role, "content": content})
        if len(history) > MAX_HISTORY_LENGTH:
            CONVERSATION_HISTORIES[patient_id] = history[-MAX_HISTORY_LENGTH:]
        return saved_message

    def save_symptom_if_present(self, patient_id: str, message: str, source_message_id: str) -> None:
        """Save patient-reported problem text without making a diagnosis."""
        normalized = message.casefold()
        if not any(keyword in normalized for keyword in HEALTH_PROBLEM_KEYWORDS):
            return

        # Each chat-message ID can produce at most one symptom log.
        already_logged = (
            self.db.query(SymptomLog)
            .filter(SymptomLog.source_message_id == source_message_id)
            .first()
        )
        if already_logged:
            return

        self.db.add(SymptomLog(
            patient_id=patient_id,
            symptom_text=message.strip(),
            source_message_id=source_message_id,
        ))
        self.db.commit()

    def execute_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        try:
            if tool_name == "get_patient_timeline":
                return tools.get_patient_timeline(patient_id=tool_args["patient_id"], db=self.db)
            if tool_name == "check_medication_conflicts":
                return tools.check_medication_conflicts(patient_id=tool_args["patient_id"], db=self.db)
            if tool_name == "recommend_specialist":
                return tools.recommend_specialist(symptoms=tool_args["symptoms"])
            if tool_name == "explain_medical_term":
                return tools.explain_medical_term(
                    term=tool_args["term"],
                    language=tool_args.get("language", "english"),
                    llm_client=self.llm,
                )
            if tool_name == "get_upcoming_followups":
                return tools.get_upcoming_followups(patient_id=tool_args["patient_id"], db=self.db)
            if tool_name == "find_nearby_doctors":
                return tools.find_nearby_doctors(
                    patient_id=tool_args["patient_id"],
                    specialty=tool_args.get("specialty"),
                    radius_km=tool_args.get("radius_km", 5),
                    db=self.db,
                )
            return {"error": f"Unknown tool: {tool_name}"}
        except Exception as exc:
            return {"error": f"Tool execution failed: {str(exc)}"}

    def _format_tool_result_for_llm(self, tool_name: str, result: Any) -> str:
        if isinstance(result, dict) and result.get("error"):
            return f"Tool error: {result['error']}"
        if tool_name == "check_medication_conflicts":
            conflicts = result.get("conflicts", [])
            return "No medication conflicts detected." if not conflicts else "Medication conflicts:\n" + "\n".join(
                f"- {item.get('message', 'Conflict found')}" for item in conflicts
            )
        if tool_name == "get_upcoming_followups":
            items = result.get("followups", [])
            return "No pending follow-ups found." if not items else "Upcoming follow-ups:\n" + "\n".join(
                f"- {item.get('action')} (due: {item.get('due_date')})" for item in items
            )
        if tool_name == "get_patient_timeline":
            events = result.get("events", [])
            return "No medical history found." if not events else "Medical history:\n" + "\n".join(
                f"- {event.get('type', 'event')}: {event.get('diagnosis') or event.get('test_name') or event.get('name') or event.get('action', '')}"
                for event in events[:10]
            )
        if tool_name == "recommend_specialist":
            items = result.get("recommendations", [])
            return "No specific specialist found; see your doctor for a referral." if not items else "Recommended specialists:\n" + "\n".join(
                f"- {item.get('department')}" for item in items
            )
        if tool_name == "explain_medical_term":
            return f"Explanation: {result.get('explanation', '')}"
        if tool_name == "find_nearby_doctors":
            places = result.get("places", [])
            return "No matching nearby healthcare facilities were found." if not places else "Nearby facilities:\n" + "\n".join(
                f"- {place.get('name')} — {place.get('distance_km')} km away; {place.get('map_url')}"
                for place in places[:5]
            )
        return json.dumps(result, indent=2, default=str)

    def _record_tool_result(self, history, name, result, calls, results, args) -> None:
        status = "failed" if isinstance(result, dict) and result.get("error") else "success"
        calls.append({"tool": name, "arguments": args, "status": status})
        results.append((name, result))
        # Tool output is useful to the model but is not saved as a patient chat message.
        history.append({"role": "user", "content": f"Tool result for {name}:\n{self._format_tool_result_for_llm(name, result)}"})

    def process_message(self, patient_id: str, user_message: str,
                        provided_history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        patient = self.get_or_create_patient(patient_id)
        if not patient:
            return {"error": f"Patient {patient_id} not found", "reply": "I couldn't find your patient record.", "tool_calls_made": [], "structured_data": {}}

        language = (patient.preferred_language or "english").lower()
        has_records = any((
            self.db.query(Medication).filter(Medication.patient_id == patient_id).first(),
            self.db.query(Consultation).filter(Consultation.patient_id == patient_id).first(),
            self.db.query(FollowUp).filter(FollowUp.patient_id == patient_id).first(),
        ))
        location_note = "Location is saved." if patient.latitude is not None and patient.longitude is not None else "No location is saved; ask the patient to save location before nearby searches."
        record_note = "Records exist; use tools before describing them." if has_records else "No medical records are on file; say so clearly."
        prompt = f"{self.SYSTEM_PROMPT}\n\nPatient: {patient.name}. Preferred language: {language}. {record_note} {location_note} Reply in {language}, unless the patient writes in another language."

        history = self.get_conversation_history(patient_id)
        saved_user_message = self.add_to_history(patient_id, "user", user_message)
        self.save_symptom_if_present(patient_id, user_message, saved_user_message.id)

        first_response = self.llm.call_with_functions(history, prompt, patient_id)
        if not first_response["success"]:
            return {"error": first_response["error"], "reply": "I encountered an error processing your request.", "tool_calls_made": [], "structured_data": {}}

        calls, results, called = [], [], set()
        for tool_call in first_response.get("tool_calls") or []:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments or "{}")

            if name == "explain_medical_term" and any(word in str(args.get("term", "")).lower() for word in CONFLICT_KEYWORDS):
                name, args = "check_medication_conflicts", {"patient_id": patient_id}
            if name in PATIENT_SCOPED_TOOLS:
                args["patient_id"] = patient_id
            if name == "explain_medical_term" and not args.get("language"):
                args["language"] = language

            result = self.execute_tool(name, args)
            called.add(name)
            self._record_tool_result(history, name, result, calls, results, args)

            if name in self.AUTO_CONFLICT_CHECK_TRIGGERS and "check_medication_conflicts" not in called:
                auto_args = {"patient_id": patient_id}
                auto = self.execute_tool("check_medication_conflicts", auto_args)
                called.add("check_medication_conflicts")
                self._record_tool_result(history, "check_medication_conflicts", auto, calls, results, auto_args)

            if name == "recommend_specialist" and "find_nearby_doctors" not in called:
                recommendations = result.get("recommendations", []) if isinstance(result, dict) else []
                specialty = recommendations[0].get("department") if recommendations else None
                nearby_args = {"patient_id": patient_id, "specialty": specialty, "radius_km": 5}
                nearby = self.execute_tool("find_nearby_doctors", nearby_args)
                called.add("find_nearby_doctors")
                self._record_tool_result(history, "find_nearby_doctors", nearby, calls, results, nearby_args)

        if calls:
            final_response = self.llm.call_with_functions(history, prompt, patient_id)
            reply = final_response.get("content") if final_response.get("success") else None
            if not reply:
                reply = "\n\n".join(self._format_tool_result_for_llm(name, result) for name, result in results)
        else:
            reply = first_response.get("content") or "How can I help you with your healthcare?"

        reply = reply.strip()
        self.add_to_history(patient_id, "assistant", reply)
        return {
            "reply": reply,
            "tool_calls_made": calls,
            "structured_data": {name: result for name, result in results},
            "timestamp": datetime.utcnow().isoformat(),
        }
