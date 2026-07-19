"""
FastAPI application for the healthcare navigation AI agent.
Provides the /agent/chat endpoint for conversational interactions.
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
import glob

from apscheduler.schedulers.background import BackgroundScheduler

from models import SessionLocal, Patient, ChatMessage, SymptomLog
from agent import HealthcareNavigationAgent
from sqlalchemy.orm import Session
import tools
import reminders


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# FastAPI app
app = FastAPI(
    title="Healthcare Navigation AI Agent",
    description="AI-powered conversational interface for healthcare navigation with function calling",
    version="1.0.0"
)

# Allow requests from any origin (needed so a frontend/demo UI or test tool
# running on a different host/port can call this API without being blocked)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ==================== BACKGROUND SCHEDULER (medication reminders) ====================
# Runs reminders.check_due_reminders() once every 60 seconds. This job opens
# its own DB session internally (see reminders.py) since it runs outside any
# HTTP request. Started in the startup event below, stopped on shutdown.
scheduler = BackgroundScheduler()


# ==================== SERVE THE CHAT FRONTEND ====================
# The HTML file (mediflow-chat.html) must sit in the same folder as this
# main.py file. This makes the whole app â€” API + chat UI â€” reachable from
# a single deployed URL, so anyone opening that URL on any device/system
# gets the working chat interface, not just localhost.

@app.get("/")
async def serve_frontend():
    """Serve the chat UI at the root URL. Looks for any file starting with
    'mediflow' so it still works even if the browser auto-renamed the
    download (e.g. 'mediflow-chat 1.html', 'mediflow-chat(1).html')."""
    folder = os.path.dirname(__file__)
    exact_path = os.path.join(folder, "mediflow-chat.html")

    if os.path.exists(exact_path):
        return FileResponse(exact_path)

    candidates = glob.glob(os.path.join(folder, "mediflow*.html"))
    if candidates:
        return FileResponse(candidates[0])

    return JSONResponse(
        status_code=404,
        content={"error": "No mediflow*.html file found next to main.py. Files here: " + str(os.listdir(folder))}
    )


# ==================== VOICE FEATURE ASSET ====================

@app.get("/voice-feature-safe.js")
async def serve_voice_feature():
    """Serve only the voice feature JavaScript; do not expose project files."""
    voice_file = os.path.join(os.path.dirname(__file__), "voice-feature-safe.js")
    if not os.path.exists(voice_file):
        raise HTTPException(status_code=404, detail="voice-feature-safe.js not found next to main.py")
    return FileResponse(voice_file, media_type="application/javascript")

# ==================== REQUEST/RESPONSE MODELS ====================

class MessageInput(BaseModel):
    """Input model for chat message."""
    patient_id: str = Field(..., description="Patient ID")
    message: str = Field(..., description="Patient's message or question")
    conversation_history: Optional[List[Dict[str, str]]] = Field(
        None,
        description="Previous conversation history in format [{'role': 'user'|'assistant', 'content': 'text'}, ...]"
    )


class ToolCall(BaseModel):
    """Record of a tool call made during processing."""
    tool: str = Field(..., description="Name of the tool called")
    arguments: Dict[str, Any] = Field(..., description="Arguments passed to the tool")
    status: str = Field(..., description="success or failed")


class ChatResponse(BaseModel):
    """Response model for chat endpoint."""
    reply: str = Field(..., description="Natural language response from the agent")
    tool_calls_made: List[ToolCall] = Field(default_factory=list, description="List of tool calls made")
    structured_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured data returned from tools"
    )
    timestamp: str = Field(..., description="ISO format timestamp")


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Additional error details")
    timestamp: str = Field(..., description="ISO format timestamp")


class PatientRegister(BaseModel):
    """Input model for registering a new patient."""
    name: str = Field(..., description="Patient's full name")
    age: Optional[int] = Field(None, description="Patient's age")
    gender: Optional[str] = Field(None, description="Patient's gender")
    phone: Optional[str] = Field(None, description="Patient's phone number")
    preferred_language: Optional[str] = Field("english", description="Preferred language for explanations")


class PatientLocationUpdate(BaseModel):
    """Browser-provided location for the nearby healthcare search."""
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    address: Optional[str] = Field(None, max_length=500)

class ReminderCreate(BaseModel):
    """Input model for creating a medication reminder. Provide EITHER
    medication_id (medicine already on file) OR medicine_name (free text,
    for a medicine not on the patient's record yet)."""
    patient_id: str = Field(..., description="Patient ID")
    medication_id: Optional[str] = Field(None, description="Medication ID this reminder is for, if it's on file")
    medicine_name: Optional[str] = Field(None, description="Free-text medicine name, if not on file yet")
    reminder_time: str = Field(..., description="Time of day in 24-hour HH:MM format, e.g. '08:00'")
    label: Optional[str] = Field(None, description="Optional note, e.g. 'with breakfast'")


# ==================== DEPENDENCIES ====================

def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_agent(db: Session = Depends(get_db)) -> HealthcareNavigationAgent:
    """Get healthcare navigation agent."""
    return HealthcareNavigationAgent(db)


# ==================== HEALTH CHECK ====================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }


# ==================== PATIENT REGISTRATION (so new/unknown users can join) ====================

@app.get("/agent/patients")
async def list_patients() -> Dict[str, Any]:
    """
    List all registered patients (id + name), so a frontend can offer
    a picker instead of requiring the user to already know a patient_id.
    """
    db = SessionLocal()
    try:
        patients = db.query(Patient).all()
        return {
            "patients": [
                {"id": p.id, "name": p.name} for p in patients
            ]
        }
    finally:
        db.close()


@app.post("/agent/register-patient")
async def register_patient(input_data: PatientRegister) -> Dict[str, Any]:
    """
    Register a brand-new patient who doesn't have a patient_id yet.
    Returns the generated patient_id, which the frontend should then use
    for all subsequent /agent/chat and /agent/upload-document calls.
    """
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


# ==================== PATIENT LOCATION ====================

@app.put("/agent/patients/{patient_id}/location")
async def update_patient_location(
    patient_id: str,
    input_data: PatientLocationUpdate,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Save a patient's location for nearby doctor/clinic searches."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")

    patient.latitude = input_data.latitude
    patient.longitude = input_data.longitude
    patient.address = input_data.address
    patient.location_updated_at = datetime.utcnow()
    db.commit()

    return {
        "patient_id": patient.id,
        "message": "Location saved successfully.",
        "latitude": patient.latitude,
        "longitude": patient.longitude,
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

        db = SessionLocal()
        patient = db.query(Patient).filter(Patient.id == input_data.patient_id).first()
        db.close()

        if not patient:
            logger.warning(f"Patient not found: {input_data.patient_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Patient {input_data.patient_id} not found"
            )

        result = agent.process_message(
            patient_id=input_data.patient_id,
            user_message=input_data.message,
            provided_history=input_data.conversation_history
        )

        if "error" in result:
            logger.error(f"Agent error: {result['error']}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result["error"]
            )

        logger.info(f"Successfully processed message. Tools used: {len(result['tool_calls_made'])}")

        response = ChatResponse(
            reply=result["reply"],
            tool_calls_made=[
                ToolCall(**tool_call) for tool_call in result["tool_calls_made"]
            ],
            structured_data=result["structured_data"],
            timestamp=result["timestamp"]
        )

        return response

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(f"Unexpected error processing message: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


# ==================== MODULE 2: DOCUMENT UPLOAD & OCR EXTRACTION ====================

@app.post("/agent/upload-document")
async def upload_document(
    patient_id: str = Form(...),
    document_type: str = Form(...),
    file: UploadFile = File(...),
):
    """
    Upload a prescription/report/discharge-summary image, run OCR + LLM
    extraction on it, and save the structured result to the database.
    For prescriptions, extracted medicines are also inserted into the
    Medication table (so check_medication_conflicts can see them).
    """
    db = SessionLocal()
    try:
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")

        if document_type not in ("prescription", "report", "discharge_summary"):
            raise HTTPException(
                status_code=400,
                detail="document_type must be one of: prescription, report, discharge_summary"
            )

        safe_name = f"{uuid.uuid4()}_{file.filename}"
        saved_path = os.path.join(UPLOAD_DIR, safe_name)
        with open(saved_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        result = tools.save_document_and_extract(
            patient_id=patient_id,
            file_path=saved_path,
            document_type=document_type,
            db=db,
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


# ==================== MEDICATIONS (lightweight list, used by the reminders UI) ====================

@app.get("/agent/medications/{patient_id}")
async def get_medications(patient_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """List a patient's medications (id + name + dosage) â€” used to populate
    the 'add a reminder' dropdown without needing a full chat round-trip."""
    from models import Medication

    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")

    meds = db.query(Medication).filter(Medication.patient_id == patient_id).all()
    return {
        "patient_id": patient_id,
        "medications": [
            {"id": m.id, "name": m.name, "dosage": m.dosage}
            for m in meds
        ],
    }


# ==================== MEDICATION REMINDERS ====================

@app.post("/agent/reminders")
async def create_reminder_endpoint(input_data: ReminderCreate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Create a daily reminder for a medication at a given time of day."""
    result = reminders.create_reminder(
        patient_id=input_data.patient_id,
        reminder_time=input_data.reminder_time,
        db=db,
        medication_id=input_data.medication_id,
        medicine_name=input_data.medicine_name,
        label=input_data.label,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/agent/reminders/{patient_id}")
async def get_reminders(patient_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """List all active reminders for a patient."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")

    return {"patient_id": patient_id, "reminders": reminders.list_reminders(patient_id, db)}


@app.delete("/agent/reminders/{reminder_id}")
async def remove_reminder(reminder_id: str, patient_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Deactivate a reminder. patient_id passed as a query param for ownership check."""
    result = reminders.delete_reminder(reminder_id=reminder_id, patient_id=patient_id, db=db)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ==================== NOTIFICATIONS ====================

@app.get("/agent/notifications/{patient_id}")
async def get_notifications(
    patient_id: str,
    unread_only: bool = False,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """List notifications for a patient (most recent first). Frontend polls this."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")

    notif_list = reminders.list_notifications(patient_id, db, unread_only=unread_only)
    unread_count = sum(1 for n in notif_list if not n["is_read"]) if not unread_only else len(notif_list)

    return {
        "patient_id": patient_id,
        "unread_count": unread_count,
        "notifications": notif_list,
    }


@app.post("/agent/notifications/{notification_id}/read")
async def read_notification(notification_id: str, patient_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Mark a notification as read. patient_id passed as a query param for ownership check."""
    result = reminders.mark_notification_read(notification_id=notification_id, patient_id=patient_id, db=db)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ==================== CONVERSATION MANAGEMENT ====================

@app.get("/agent/conversation/{patient_id}")
async def get_conversation_history(
    patient_id: str,
    agent: HealthcareNavigationAgent = Depends(get_agent)
) -> Dict[str, Any]:
    """Get conversation history for a patient."""
    try:
        db = SessionLocal()
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        db.close()

        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Patient {patient_id} not found"
            )

        history = agent.get_conversation_history(patient_id)

        return {
            "patient_id": patient_id,
            "patient_name": patient.name,
            "message_count": len(history),
            "conversation_history": history
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(f"Error retrieving conversation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@app.delete("/agent/conversation/{patient_id}")
async def clear_conversation_history(
    patient_id: str,
    agent: HealthcareNavigationAgent = Depends(get_agent),
    db: Session = Depends(get_db),
) -> Dict[str, str]:
    """Delete this patient's persistent chat history and symptom logs."""
    from agent import CONVERSATION_HISTORIES

    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient {patient_id} not found",
        )

    db.query(SymptomLog).filter(SymptomLog.patient_id == patient_id).delete(
        synchronize_session=False
    )
    db.query(ChatMessage).filter(ChatMessage.patient_id == patient_id).delete(
        synchronize_session=False
    )
    db.commit()
    CONVERSATION_HISTORIES.pop(patient_id, None)

    return {
        "status": "success",
        "message": "Saved conversation history and symptom logs were cleared.",
    }

# ==================== TOOL DOCUMENTATION ====================

@app.get("/agent/tools")
async def list_available_tools() -> Dict[str, Any]:
    """Get documentation about available tools."""
    from llm import TOOLS_SCHEMA

    return {
        "total_tools": len(TOOLS_SCHEMA),
        "tools": [
            {
                "name": tool["function"]["name"],
                "description": tool["function"]["description"],
                "parameters": tool["function"]["parameters"]
            }
            for tool in TOOLS_SCHEMA
        ]
    }


# ==================== ERROR HANDLERS ====================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "timestamp": datetime.utcnow().isoformat()
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle unexpected exceptions."""
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "timestamp": datetime.utcnow().isoformat()
        }
    )


# ==================== STARTUP/SHUTDOWN ====================

@app.on_event("startup")
async def startup_event():
    """Startup event handler."""
    logger.info("Healthcare Navigation AI Agent starting up")
    logger.info("Available endpoints:")
    logger.info("  POST   /agent/chat - Process patient message")
    logger.info("  POST   /agent/upload-document - Upload & extract a medical document")
    logger.info("  POST   /agent/reminders - Create a medication reminder")
    logger.info("  GET    /agent/reminders/{patient_id} - List reminders")
    logger.info("  DELETE /agent/reminders/{reminder_id} - Delete a reminder")
    logger.info("  GET    /agent/notifications/{patient_id} - List notifications")
    logger.info("  POST   /agent/notifications/{notification_id}/read - Mark notification read")
    logger.info("  GET    /agent/conversation/{patient_id} - Get conversation history")
    logger.info("  DELETE /agent/conversation/{patient_id} - Clear conversation history")
    logger.info("  GET    /agent/tools - List available tools")
    logger.info("  GET    /health - Health check")

    # Start the background scheduler that checks medication reminders every
    # 60 seconds and generates Notification rows when they're due.
    scheduler.add_job(reminders.check_due_reminders, "interval", seconds=60, id="reminder_check")
    scheduler.start()
    logger.info("Reminder scheduler started (checking every 60 seconds)")


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler."""
    scheduler.shutdown(wait=False)
    logger.info("Reminder scheduler stopped")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

