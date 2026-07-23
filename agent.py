"""Core AI agent: tool calling, session-based chat history, and symptom logging."""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

import tools
from llm import get_llm_client
from models import ChatMessage, ChatSession, Consultation, FollowUp, Medication, Patient, SymptomLog

CONVERSATION_HISTORIES: Dict[str, List[Dict[str, str]]] = {}  # keyed by session_id
MAX_HISTORY_LENGTH = 10
CONFLICT_KEYWORDS = ("conflict", "interact", "clash", "duplicate", "safe together", "safety")
PATIENT_SCOPED_TOOLS = {
    "get_patient_timeline", "check_medication_conflicts",
    "get_upcoming_followups", "find_nearby_doctors",
}

HEALTH_PROBLEM_KEYWORDS = (
    "pain", "ache", "fever", "cough", "cold", "headache", "migraine", "dizzy",
    "dizziness", "vomit", "vomiting", "nausea", "diarrhea", "weakness", "fatigue",
    "breath", "breathing", "chest", "rash", "swelling", "bleeding", "infection",
    "diabetes", "hypertension", "asthma", "anxiety", "depression", "symptom",
    "dard", "bukhar", "khansi", "sar dard", "chakkar", "ulti", "kamzori",
    "saans", "sujan", "jalan", "bimari", "problem", "takleef",
)

DEFAULT_SESSION_TITLE = "New Chat"


class HealthcareNavigationAgent:
    SYSTEM_PROMPT = """You are a helpful healthcare navigation assistant for patients and their families.

You answer two kinds of questions:

1. Questions about THIS patient's own records (history, medication conflicts,
   follow-ups, nearby facilities). Use the available tools for these and
   base your answer only on what the tools return.

2. General health questions — including about a family member, a friend, or
   a hypothetical situation, or any "what should I do if..." question that
   is NOT about this patient's own stored records. For these, you MUST still
   give a genuinely helpful answer. Never simply deflect with "see a doctor"
   and nothing else. For a general symptom question, always include:
   (a) a short, plain-language explanation of common possible causes,
   (b) simple, safe general self-care/home-care steps,
   (c) clear red-flag signs that mean they should see a doctor urgently or
       go to the ER right away.

Do not diagnose a specific individual, do not prescribe medicine doses or
brand names, and do not present directory results as emergency care. Use
plain, warm, empathetic language. If symptoms sound severe or an emergency
(e.g. sudden vision loss, chest pain with breathlessness, severe bleeding,
signs of stroke), say clearly that they should seek emergency care immediately.

Use get_patient_timeline for medical history; check_medication_conflicts for
medicine interaction/safety questions; recommend_specialist for symptoms
related to THIS patient; explain_medical_term only for a term or medicine
definition; get_upcoming_followups for future tasks; and find_nearby_doctors
for nearby doctors, clinics, hospitals, pharmacies, or diagnostic labs. Do
NOT use patient-record tools for questions about someone who is not this
patient — just answer directly with general guidance instead."""

    AUTO_CONFLICT_CHECK_TRIGGERS = {"get_patient_timeline"}

    def __init__(self, db: Session):
        self.db = db
        self.llm = get_llm_client()

    def get_or_create_patient(self, patient_id: str) -> Optional[Patient]:
        return self.db.query(Patient).filter(Patient.id == patient_id).first()

    # ---------------- SESSION MANAGEMENT ----------------

    def create_session(self, patient_id: str) -> ChatSession:
        """Start a brand-new chat thread ('New Chat' button)."""
        session = ChatSession(patient_id=patient_id, title=DEFAULT_SESSION_TITLE)
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_or_create_session(self, patient_id: str, session_id: Optional[str]) -> ChatSession:
        if session_id:
            session = self.db.query(ChatSession).filter(
                ChatSession.id == session_id,
                ChatSession.patient_id == patient_id,
                ChatSession.is_archived == False,
            ).first()
            if session:
                return session
        return self.create_session(patient_id)

    def list_sessions(self, patient_id: str) -> List[Dict[str, Any]]:
        """For the sidebar: most recently active chat first."""
        sessions = (
            self.db.query(ChatSession)
            .filter(ChatSession.patient_id == patient_id, ChatSession.is_archived == False)
            .order_by(ChatSession.last_message_at.desc())
            .all()
        )
        return [
            {
                "session_id": s.id,
                "title": s.title or DEFAULT_SESSION_TITLE,
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat(),
                "last_message_at": s.last_message_at.isoformat() if s.last_message_at else None,
            }
            for s in sessions
        ]

    def delete_session(self, patient_id: str, session_id: str) -> bool:
        session = self.db.query(ChatSession).filter(
            ChatSession.id == session_id, ChatSession.patient_id == patient_id
        ).first()
        if not session:
            return False
        self.db.delete(session)
        self.db.commit()
        CONVERSATION_HISTORIES.pop(session_id, None)
        return True

    # ---------------- MESSAGE HISTORY (per session) ----------------

    def get_conversation_history(self, session_id: str) -> List[Dict[str, str]]:
        if session_id not in CONVERSATION_HISTORIES:
            messages = (
                self.db.query(ChatMessage)
                .filter(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.desc())
                .limit(MAX_HISTORY_LENGTH)
                .all()
            )
            messages.reverse()
            CONVERSATION_HISTORIES[session_id] = [
                {"role": message.role, "content": message.content}
                for message in messages
            ]
        return CONVERSATION_HISTORIES[session_id]

    def get_full_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """Full history for loading a session clicked in the sidebar — not
        capped at MAX_HISTORY_LENGTH, the user should see everything."""
        messages = (
            self.db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )
        return [
            {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
            for m in messages
        ]

    def add_to_history(self, session_id: str, patient_id: str, role: str, content: str) -> ChatMessage:
        saved_message = ChatMessage(patient_id=patient_id, session_id=session_id, role=role, content=content)
        self.db.add(saved_message)

        session = self.db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if session:
            now = datetime.utcnow()
            session.updated_at = now
            session.last_message_at = now
            if (not session.title or session.title == DEFAULT_SESSION_TITLE) and role == "user":
                session.title = content.strip()[:60] + ("..." if len(content.strip()) > 60 else "")

        self.db.commit()
        self.db.refresh(saved_message)

        history = self.get_conversation_history(session_id)
        history.append({"role": role, "content": content})
        if len(history) > MAX_HISTORY_LENGTH:
            CONVERSATION_HISTORIES[session_id] = history[-MAX_HISTORY_LENGTH:]
        return saved_message

    def save_symptom_if_present(self, patient_id: str, message: str, source_message_id: str) -> None:
        normalized = message.casefold()
        if not any(keyword in normalized for keyword in HEALTH_PROBLEM_KEYWORDS):
            return

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

    # ---------------- TOOLS ----------------

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
                    facility_type=tool_args.get("facility_type"),
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
        history.append({"role": "user", "content": f"Tool result for {name}:\n{self._format_tool_result_for_llm(name, result)}"})

    # ---------------- MAIN ENTRY POINT ----------------

    def process_message(self, patient_id: str, user_message: str,
                        session_id: Optional[str] = None,
                        provided_history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        patient = self.get_or_create_patient(patient_id)
        if not patient:
            return {"error": f"Patient {patient_id} not found", "reply": "I couldn't find your patient record.",
                    "tool_calls_made": [], "structured_data": {}, "session_id": session_id}

        session = self.get_or_create_session(patient_id, session_id)
        session_id = session.id

        language = (patient.preferred_language or "english").lower()
        has_records = any((
            self.db.query(Medication).filter(Medication.patient_id == patient_id).first(),
            self.db.query(Consultation).filter(Consultation.patient_id == patient_id).first(),
            self.db.query(FollowUp).filter(FollowUp.patient_id == patient_id).first(),
        ))
        location_note = "Location is saved." if patient.latitude is not None and patient.longitude is not None else "No GPS location saved; a saved address will be used as fallback if present."
        record_note = "Records exist; use tools before describing them." if has_records else "No medical records are on file for this patient; say so clearly if asked about their own history."
        prompt = f"{self.SYSTEM_PROMPT}\n\nPatient: {patient.name}. Preferred language: {language}. {record_note} {location_note} Reply in {language}, unless the patient writes in another language."

        history = self.get_conversation_history(session_id)
        saved_user_message = self.add_to_history(session_id, patient_id, "user", user_message)
        self.save_symptom_if_present(patient_id, user_message, saved_user_message.id)

        first_response = self.llm.call_with_functions(history, prompt, patient_id)
        if not first_response["success"]:
            if first_response.get("error") == "rate_limited":
                wait_seconds = first_response.get("retry_after_seconds")
                if wait_seconds:
                    wait_text = f"about {int(wait_seconds // 60)} minute(s)" if wait_seconds >= 60 else f"about {int(wait_seconds)} seconds"
                    friendly_reply = f"I'm getting a lot of requests right now and need to slow down — please try again in {wait_text}. Your message wasn't lost; just resend it then."
                else:
                    friendly_reply = "I'm getting a lot of requests right now and need to slow down — please try again in a few minutes."
                return {"error": "rate_limited", "reply": friendly_reply, "tool_calls_made": [], "structured_data": {}, "session_id": session_id}
            return {"error": first_response["error"], "reply": "I encountered an error processing your request.",
                    "tool_calls_made": [], "structured_data": {}, "session_id": session_id}

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
            final_response = self.llm.call_with_functions(history, prompt, patient_id, use_tools=False)
            reply = final_response.get("content") if final_response.get("success") else None
            if not reply:
                reply = "\n\n".join(self._format_tool_result_for_llm(name, result) for name, result in results)
                if final_response.get("error") == "rate_limited":
                    reply += "\n\n(I'm rate-limited right now, so here's the raw data above without a written summary.)"
        else:
            reply = first_response.get("content") or "How can I help you with your healthcare?"

        reply = reply.strip()
        self.add_to_history(session_id, patient_id, "assistant", reply)
        return {
            "reply": reply,
            "tool_calls_made": calls,
            "structured_data": {name: result for name, result in results},
            "timestamp": datetime.utcnow().isoformat(),
            "session_id": session_id,
        }