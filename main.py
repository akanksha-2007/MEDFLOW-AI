"""
FastAPI application for the healthcare navigation AI agent.
Provides the /agent/chat endpoint for conversational interactions, plus
persistent chat-session management (new chat, list sessions, per-session history),
document upload with OCR extraction, nearby-facility location search, and a
patient care-journey dashboard.
"""

from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from datetime import datetime
import logging
import shutil
import uuid
import os

from models import SessionLocal, Patient, ChatSession
from agent import HealthcareNavigationAgent
from sqlalchemy.orm import Session
import tools


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


app = FastAPI(
    title="Healthcare Navigation AI Agent",
    description="AI-powered conversational interface for healthcare navigation with function calling",
    version="1.3.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ==================== SERVE THE CHAT FRONTEND ====================

@app.get("/")
async def serve_frontend():
    """Serve the chat UI at the root URL."""
    html_path = os.path.join(os.path.dirname(__file__), "mediflow-chat.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return JSONResponse(status_code=404, content={"error": "mediflow-chat.html not found next to main.py"})


# ==================== REQUEST/RESPONSE MODELS ====================

class MessageInput(BaseModel):
    """Input model for chat message."""
    patient_id: str = Field(..., description="Patient ID")
    message: str = Field(..., description="Patient's message or question")
    session_id: Optional[str] = Field(
        None,
        description="Which chat session to continue. Omit to use the patient's most recent active session."
    )


class ToolCall(BaseModel):
    tool: str = Field(..., description="Name of the tool called")
    arguments: Dict[str, Any] = Field(..., description="Arguments passed to the tool")
    status: str = Field(..., description="success or failed")


class ChatResponse(BaseModel):
    reply: str = Field(..., description="Natural language response from the agent")
    tool_calls_made: List[ToolCall] = Field(default_factory=list)
    structured_data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str
    session_id: str = Field(..., description="The chat session this exchange belongs to")


class PatientRegister(BaseModel):
    name: str = Field(..., description="Patient's full name")
    age: Optional[int] = Field(None, description="Patient's age")
    gender: Optional[str] = Field(None, description="Patient's gender")
    phone: Optional[str] = Field(None, description="Patient's phone number")
    preferred_language: Optional[str] = Field("english", description="Preferred language for explanations")


class NewSessionInput(BaseModel):
    patient_id: str = Field(..., description="Patient ID")
    title: Optional[str] = Field("New Chat", description="Optional title for the new chat session")


class LocationInput(BaseModel):
    patient_id: str = Field(..., description="Patient ID")
    address: str = Field(..., description="Free-text address, any city, India or international")


# ==================== DEPENDENCIES ====================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_agent(db: Session = Depends(get_db)) -> HealthcareNavigationAgent:
    return HealthcareNavigationAgent(db)


# ==================== HEALTH CHECK ====================

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# ==================== PATIENT REGISTRATION ====================

@app.get("/agent/patients")
async def list_patients() -> Dict[str, Any]:
    """List all registered patients (id, name, preferred_language)."""
    db = SessionLocal()
    try:
        patients = db.query(Patient).all()
        return {
            "patients": [
                {"id": p.id, "name": p.name, "preferred_language": p.preferred_language or "english"}
                for p in patients
            ]
        }
    finally:
        db.close()


@app.post("/agent/register-patient")
async def register_patient(input_data: PatientRegister) -> Dict[str, Any]:
    """Register a brand-new patient and return their generated patient_id."""
    db = SessionLocal()
    try:
        new_patient = Patient(
            name=input_data.name,
            age=input_data.age,
            gender=input_data.gender,
            phone=input_data.phone,
            preferred_language=input_data.preferred_language or "english",
        )
        db.add(new_patient)
        db.commit()
        db.refresh(new_patient)
        return {
            "patient_id": new_patient.id,
            "name": new_patient.name,
            "message": "Patient registered successfully. Use this patient_id for future requests."
        }
    finally:
        db.close()


# ==================== LOCATION / NEARBY FACILITIES ====================

@app.post("/agent/update-location")
async def update_location(input_data: LocationInput) -> Dict[str, Any]:
    """Save/update a patient's address — geocodes it to lat/lon via OpenStreetMap so
    nearby-facility search works, for any city worldwide."""
    db = SessionLocal()
    try:
        patient = db.query(Patient).filter(Patient.id == input_data.patient_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail=f"Patient {input_data.patient_id} not found")

        geo = tools.geocode_address(input_data.address)
        if "error" in geo:
            raise HTTPException(status_code=422, detail=geo["error"])

        patient.address = geo["display_name"]
        patient.latitude = geo["latitude"]
        patient.longitude = geo["longitude"]
        patient.location_updated_at = datetime.utcnow()
        db.commit()

        return {
            "status": "success",
            "address": patient.address,
            "latitude": patient.latitude,
            "longitude": patient.longitude,
        }
    except HTTPException:
        raise
    finally:
        db.close()


@app.get("/agent/nearby-facilities/{patient_id}")
async def nearby_facilities(patient_id: str, facility_type: str = "hospital") -> Dict[str, Any]:
    """Find real nearby hospitals, pharmacies, clinics, or diagnostic labs for a patient's saved location."""
    db = SessionLocal()
    try:
        result = tools.find_nearby_facilities(patient_id, facility_type, db)
        if "error" in result:
            raise HTTPException(status_code=422, detail=result["error"])
        return result
    except HTTPException:
        raise
    finally:
        db.close()


# ==================== DASHBOARD ====================

@app.get("/agent/dashboard/{patient_id}")
async def get_patient_dashboard(patient_id: str) -> Dict[str, Any]:
    """Get the patient's care journey dashboard: completed consultations, pending
    appointments, active medications, upcoming follow-ups, and diagnostic history."""
    db = SessionLocal()
    try:
        result = tools.get_patient_dashboard(patient_id, db)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    finally:
        db.close()


# ==================== CHAT SESSIONS (persistent history, "New Chat") ====================

@app.post("/agent/chat/new-session")
async def new_chat_session(
    input_data: NewSessionInput,
    agent: HealthcareNavigationAgent = Depends(get_agent)
) -> Dict[str, Any]:
    """
    Start a fresh chat session for a patient. Old sessions and their
    messages are kept — nothing is deleted, this just switches new
    messages into a clean conversation (like opening a new chat tab).
    """
    patient = agent.get_or_create_patient(input_data.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {input_data.patient_id} not found")

    session = agent.start_new_session(input_data.patient_id, title=input_data.title or "New Chat")
    return {"session_id": session.id, "title": session.title, "created_at": session.created_at.isoformat()}


@app.get("/agent/chat/sessions/{patient_id}")
async def list_chat_sessions(
    patient_id: str,
    agent: HealthcareNavigationAgent = Depends(get_agent)
) -> Dict[str, Any]:
    """
    List all of a patient's past + active chat sessions, most recent first.
    Each session includes its full message list, so the frontend can load
    a session's history directly without a second round-trip.
    """
    patient = agent.get_or_create_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")

    sessions = agent.list_sessions(patient_id)
    return {
        "sessions": [
            {
                "id": s.id,
                "title": s.title,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "last_message_at": s.last_message_at.isoformat() if s.last_message_at else None,
                "is_archived": s.is_archived,
                "messages": agent.get_session_history(s.id),
            }
            for s in sessions
        ]
    }


# ==================== MAIN AGENT ENDPOINT ====================

@app.post("/agent/chat", response_model=ChatResponse)
async def agent_chat(
    input_data: MessageInput,
    agent: HealthcareNavigationAgent = Depends(get_agent)
) -> ChatResponse:
    """Process a patient message through the healthcare navigation agent."""
    try:
        logger.info(f"Processing message for patient {input_data.patient_id}")

        patient = agent.get_or_create_patient(input_data.patient_id)
        if not patient:
            logger.warning(f"Patient not found: {input_data.patient_id}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Patient {input_data.patient_id} not found")

        result = agent.process_message(
            patient_id=input_data.patient_id,
            user_message=input_data.message,
            session_id=input_data.session_id,
        )

        if "error" in result:
            logger.error(f"Agent error: {result['error']}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=result["error"])

        logger.info(f"Successfully processed message. Tools used: {len(result['tool_calls_made'])}")

        return ChatResponse(
            reply=result["reply"],
            tool_calls_made=[ToolCall(**tc) for tc in result["tool_calls_made"]],
            structured_data=result["structured_data"],
            timestamp=result["timestamp"],
            session_id=result["session_id"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error processing message: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal server error: {str(e)}")


# ==================== MODULE 2: DOCUMENT UPLOAD & OCR EXTRACTION ====================

@app.post("/agent/upload-document")
async def upload_document(
    patient_id: str = Form(...),
    document_type: str = Form(...),
    file: UploadFile = File(...),
):
    """Upload a prescription/report/discharge-summary image, run OCR + LLM extraction, save results."""
    db = SessionLocal()
    try:
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")

        if document_type not in ("prescription", "report", "discharge_summary"):
            raise HTTPException(status_code=400, detail="document_type must be one of: prescription, report, discharge_summary")

        safe_name = f"{uuid.uuid4()}_{file.filename}"
        saved_path = os.path.join(UPLOAD_DIR, safe_name)
        with open(saved_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        result = tools.save_document_and_extract(
            patient_id=patient_id, file_path=saved_path, document_type=document_type, db=db,
        )

        if "error" in result:
            raise HTTPException(status_code=422, detail=result["error"])
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error during document upload: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
    finally:
        db.close()


# ==================== CONVERSATION HISTORY ====================

@app.get("/agent/conversation/{patient_id}")
async def get_conversation_history(
    patient_id: str,
    session_id: Optional[str] = None,
    agent: HealthcareNavigationAgent = Depends(get_agent)
) -> Dict[str, Any]:
    """
    Get conversation history for a patient. If session_id is omitted, returns
    the patient's current active session (creating one if they have none yet).
    """
    try:
        patient = agent.get_or_create_patient(patient_id)
        if not patient:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Patient {patient_id} not found")

        if session_id:
            session = agent.db.query(ChatSession).filter(
                ChatSession.id == session_id, ChatSession.patient_id == patient_id
            ).first()
            if not session:
                raise HTTPException(status_code=404, detail="Session not found for this patient")
        else:
            session = agent.get_or_create_active_session(patient_id)

        history = agent.get_session_history(session.id)

        return {
            "patient_id": patient_id,
            "patient_name": patient.name,
            "session_id": session.id,
            "message_count": len(history),
            "conversation_history": history
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error retrieving conversation: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal server error: {str(e)}")


@app.delete("/agent/conversation/{patient_id}")
async def archive_active_session(
    patient_id: str,
    agent: HealthcareNavigationAgent = Depends(get_agent)
) -> Dict[str, str]:
    """
    Archive the patient's current active session (equivalent to starting a
    fresh chat). The old conversation is NOT deleted — it stays in the
    database and can still be viewed via /agent/chat/sessions/{patient_id}.
    """
    try:
        patient = agent.get_or_create_patient(patient_id)
        if not patient:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Patient {patient_id} not found")

        active = agent.get_active_session(patient_id)
        if active:
            active.is_archived = True
            agent.db.commit()

        return {"status": "success", "message": f"Started a fresh conversation for patient {patient_id}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error archiving conversation: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal server error: {str(e)}")


# ==================== TOOL DOCUMENTATION ====================

@app.get("/agent/tools")
async def list_available_tools() -> Dict[str, Any]:
    from llm import TOOLS_SCHEMA
    return {
        "total_tools": len(TOOLS_SCHEMA),
        "tools": [
            {"name": t["function"]["name"], "description": t["function"]["description"], "parameters": t["function"]["parameters"]}
            for t in TOOLS_SCHEMA
        ]
    }


# ==================== ERROR HANDLERS ====================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail, "timestamp": datetime.utcnow().isoformat()})


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.exception("Unhandled exception")
    return JSONResponse(status_code=500, content={"error": "Internal server error", "timestamp": datetime.utcnow().isoformat()})


# ==================== STARTUP ====================

@app.on_event("startup")
async def startup_event():
    logger.info("Healthcare Navigation AI Agent starting up")
    logger.info("Available endpoints:")
    logger.info("  POST   /agent/chat - Process patient message (persisted per session)")
    logger.info("  POST   /agent/chat/new-session - Start a fresh chat session")
    logger.info("  GET    /agent/chat/sessions/{patient_id} - List a patient's chat sessions (with messages)")
    logger.info("  POST   /agent/upload-document - Upload & extract a medical document")
    logger.info("  POST   /agent/update-location - Save/geocode a patient's address")
    logger.info("  GET    /agent/nearby-facilities/{patient_id} - Find nearby hospitals/pharmacies/clinics/labs")
    logger.info("  GET    /agent/dashboard/{patient_id} - Patient care journey dashboard")
    logger.info("  GET    /agent/conversation/{patient_id} - Get conversation history")
    logger.info("  DELETE /agent/conversation/{patient_id} - Archive active session (start fresh)")
    logger.info("  GET    /agent/tools - List available tools")
    logger.info("  GET    /health - Health check")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)