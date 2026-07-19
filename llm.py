"""LLM integration with Groq function calling capabilities."""
import os
from enum import Enum
from typing import Any, Dict, List, Optional


class ToolType(str, Enum):
    GET_PATIENT_TIMELINE = "get_patient_timeline"
    CHECK_MEDICATION_CONFLICTS = "check_medication_conflicts"
    RECOMMEND_SPECIALIST = "recommend_specialist"
    EXPLAIN_MEDICAL_TERM = "explain_medical_term"
    GET_UPCOMING_FOLLOWUPS = "get_upcoming_followups"
    FIND_NEARBY_DOCTORS = "find_nearby_doctors"


TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_patient_timeline",
            "description": "Get all medical events for a patient in chronological order: consultations, medications, tests, follow-ups.",
            "parameters": {"type": "object", "properties": {"patient_id": {"type": "string", "description": "The unique identifier of the patient"}}, "required": ["patient_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_medication_conflicts",
            "description": "Use whenever the patient asks if their own medicines conflict, interact, clash, duplicate, or are safe together. This checks actual prescription records.",
            "parameters": {"type": "object", "properties": {"patient_id": {"type": "string", "description": "The unique identifier of the patient"}}, "required": ["patient_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_specialist",
            "description": "Get recommended medical departments/specialists based on described symptoms. Use when patient mentions symptoms.",
            "parameters": {"type": "object", "properties": {"symptoms": {"type": "string", "description": "Patient description of symptoms or health concerns"}}, "required": ["symptoms"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_medical_term",
            "description": "Use only to define a specific medical term, medicine name, or diagnosis in plain language. Never use it for medicine interaction or safety questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "term": {"type": "string", "description": "The medical term, medicine name, or diagnosis to explain"},
                    "language": {"type": "string", "description": "Language code, for example english or hindi", "default": "english"},
                },
                "required": ["term"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_upcoming_followups",
            "description": "Get pending follow-ups and upcoming appointments/tasks due in the next 30 days.",
            "parameters": {"type": "object", "properties": {"patient_id": {"type": "string", "description": "The unique identifier of the patient"}}, "required": ["patient_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_nearby_doctors",
            "description": "Find nearby doctors, clinics, and hospitals using the patient's saved location. Use when the patient asks for a nearby doctor, clinic, hospital, medical facility, or local specialist. This is directory information, not an emergency service.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_id": {"type": "string", "description": "The unique identifier of the patient"},
                    "specialty": {"type": "string", "description": "Optional specialty, such as cardiology or dermatology"},
                    "radius_km": {"type": "number", "description": "Search radius in kilometres; default 5, maximum 20", "default": 5},
                },
                "required": ["patient_id"],
            },
        },
    },
]


class GroqClient:
    """Wrapper around Groq's OpenAI-compatible function-calling API."""

    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY", "")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY environment variable not set")
        try:
            from groq import Groq
            self.client = Groq(api_key=self.api_key)
        except ImportError as exc:
            raise ImportError("Please install groq: pip install groq") from exc

    def call_with_functions(self, messages: List[Dict[str, str]], system_prompt: str,
                            patient_id: str = None) -> Dict[str, Any]:
        last_error = None
        for attempt in range(2):
            try:
                response = self.client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "system", "content": system_prompt}, *messages],
                    tools=TOOLS_SCHEMA,
                    tool_choice="auto",
                    temperature=0.2,
                )
                message = response.choices[0].message
                return {
                    "success": True,
                    "response": response,
                    "finish_reason": response.choices[0].finish_reason,
                    "content": message.content,
                    "tool_calls": message.tool_calls,
                }
            except Exception as exc:
                last_error = exc
                if "tool_use_failed" in str(exc) and attempt == 0:
                    continue
                break
        return {"success": False, "error": str(last_error)}


_llm_client: Optional[GroqClient] = None


def get_llm_client() -> GroqClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = GroqClient()
    return _llm_client
