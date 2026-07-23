"""LLM integration with Groq function calling capabilities."""
import os
import re
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
            "description": "Find nearby doctors, clinics, hospitals, pharmacies, or diagnostic labs using the patient's saved location or address. Use when the patient asks for a nearby doctor, clinic, hospital, pharmacy, lab, or local specialist. This is directory information, not an emergency service.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_id": {"type": "string", "description": "The unique identifier of the patient"},
                    "specialty": {"type": "string", "description": "Optional medical specialty, such as cardiology or dermatology"},
                    "facility_type": {
                        "type": "string",
                        "enum": ["hospital", "pharmacy", "clinic", "doctor", "diagnostic_center", "any"],
                        "description": "Type of facility to search for. Use 'any' if the patient didn't specify.",
                        "default": "any",
                    },
                    "radius_km": {"type": "number", "description": "Search radius in kilometres; default 5, maximum 20", "default": 5},
                },
                "required": ["patient_id"],
            },
        },
    },
]

# If the primary model is out of daily tokens, retry once on a smaller model
# before giving up. Both are free-tier Groq models; the 8b model uses far
# fewer tokens per call, so it often still has quota left.
PRIMARY_MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "llama-3.1-8b-instant"


def _extract_retry_after(error_message: str) -> Optional[float]:
    """Best-effort parse of Groq's 'try again in Xm Y.Zs' text."""
    match = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", error_message)
    if not match:
        return None
    minutes = float(match.group(1)) if match.group(1) else 0
    seconds = float(match.group(2))
    return minutes * 60 + seconds


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

    def _call_model(self, model: str, messages: List[Dict[str, str]], system_prompt: str,
                    use_tools: bool = True) -> Dict[str, Any]:
        request_kwargs = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "temperature": 0.2,
        }
        if use_tools:
            request_kwargs["tools"] = TOOLS_SCHEMA
            request_kwargs["tool_choice"] = "auto"

        response = self.client.chat.completions.create(**request_kwargs)
        message = response.choices[0].message
        return {
            "success": True,
            "response": response,
            "finish_reason": response.choices[0].finish_reason,
            "content": message.content,
            "tool_calls": message.tool_calls,
        }

    def call_with_functions(self, messages: List[Dict[str, str]], system_prompt: str,
                            patient_id: str = None, use_tools: bool = True) -> Dict[str, Any]:
        """
        use_tools=True (default): model may call a tool from TOOLS_SCHEMA.
        use_tools=False: model is forced to respond with plain text only —
        useful for a second pass after a tool result was already fed back in.
        """
        models_to_try = [PRIMARY_MODEL, FALLBACK_MODEL]
        last_error = None
        last_retry_after = None

        for model in models_to_try:
            for attempt in range(2):
                try:
                    return self._call_model(model, messages, system_prompt, use_tools)
                except Exception as exc:
                    error_text = str(exc)
                    last_error = exc

                    if "rate_limit_exceeded" in error_text or "429" in error_text:
                        last_retry_after = _extract_retry_after(error_text)
                        break  # rate limited — skip to next model, don't retry this one

                    if "tool_use_failed" in error_text and attempt == 0:
                        continue  # transient formatting glitch, retry same model once

                    break

        error_text = str(last_error)
        if "rate_limit_exceeded" in error_text or "429" in error_text:
            return {
                "success": False,
                "error": "rate_limited",
                "retry_after_seconds": last_retry_after,
                "raw_error": error_text,
            }
        return {"success": False, "error": error_text}


_llm_client: Optional[GroqClient] = None


def get_llm_client() -> GroqClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = GroqClient()
    return _llm_client