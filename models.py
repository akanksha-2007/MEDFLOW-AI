"""Healthcare navigation system database models."""
from dotenv import load_dotenv
load_dotenv()

from datetime import datetime
import enum
import uuid

from sqlalchemy import Boolean, Column, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text, Time, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker


def generate_uuid() -> str:
    return str(uuid.uuid4())


Base = declarative_base()
DATABASE_URL = "sqlite:///./healthcare_v2.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class DocumentType(str, enum.Enum):
    PRESCRIPTION = "prescription"
    REPORT = "report"
    DISCHARGE_SUMMARY = "discharge_summary"


class Patient(Base):
    __tablename__ = "patients"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    name = Column(String, index=True)
    age = Column(Integer)
    date_of_birth = Column(DateTime)
    gender = Column(String)
    phone = Column(String)
    email = Column(String)
    preferred_language = Column(String, default="english")

    address = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_updated_at = Column(DateTime, nullable=True)

    consultations = relationship("Consultation", back_populates="patient")
    medications = relationship("Medication", back_populates="patient")
    tests = relationship("Test", back_populates="patient")
    followups = relationship("FollowUp", back_populates="patient")
    documents = relationship("MedicalDocument", back_populates="patient")
    reminders = relationship("MedicationReminder", back_populates="patient")
    notifications = relationship("Notification", back_populates="patient")

    chat_sessions = relationship("ChatSession", back_populates="patient", cascade="all, delete-orphan")
    chat_messages = relationship("ChatMessage", back_populates="patient", cascade="all, delete-orphan")
    symptom_logs = relationship("SymptomLog", back_populates="patient", cascade="all, delete-orphan")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False, index=True)
    title = Column(String, default="New Chat")
    preferred_language = Column(String, default="auto")
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_message_at = Column(DateTime, default=datetime.utcnow)
    is_archived = Column(Boolean, default=False)

    patient = relationship("Patient", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class Consultation(Base):
    __tablename__ = "consultations"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False, index=True)
    date = Column(DateTime, default=datetime.utcnow, index=True)
    doctor_name = Column(String, nullable=False)
    department = Column(String, nullable=True)
    chief_complaint = Column(Text, nullable=True)
    diagnosis = Column(Text, nullable=True)
    treatment_plan = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    patient = relationship("Patient", back_populates="consultations")
    medications = relationship("Medication", back_populates="consultation", cascade="all, delete-orphan")


class Medication(Base):
    __tablename__ = "medications"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"))
    consultation_id = Column(String, ForeignKey("consultations.id"), nullable=True)
    name = Column(String, index=True)
    dosage = Column(String)
    frequency = Column(String)
    start_date = Column(DateTime)
    end_date = Column(DateTime, nullable=True)
    indication = Column(String)
    notes = Column(Text)
    prescribed_by = Column(String, nullable=True)
    source_document_id = Column(String, ForeignKey("medical_documents.id"), nullable=True)

    patient = relationship("Patient", back_populates="medications")
    consultation = relationship("Consultation", back_populates="medications")
    reminders = relationship("MedicationReminder", back_populates="medication")
    source_document = relationship("MedicalDocument", back_populates="medications")


class Test(Base):
    __tablename__ = "tests"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False, index=True)
    test_name = Column(String, nullable=False, index=True)
    ordered_date = Column(DateTime, default=datetime.utcnow)
    scheduled_date = Column(DateTime, nullable=True)
    completed_date = Column(DateTime, nullable=True)
    result_status = Column(String, nullable=True)
    result_value = Column(String, nullable=True)
    reference_range = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

    patient = relationship("Patient", back_populates="tests")


class FollowUp(Base):
    __tablename__ = "followups"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False, index=True)
    due_date = Column(DateTime, nullable=False, index=True)
    action = Column(String, nullable=False)
    status = Column(String, default="Pending")
    priority = Column(String, default="Normal")
    notes = Column(Text, nullable=True)
    created_date = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="followups")


class MedicalDocument(Base):
    __tablename__ = "medical_documents"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False, index=True)
    file_url = Column(String, nullable=False)
    document_type = Column(Enum(DocumentType), nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    ocr_extracted_text = Column(Text, nullable=True)
    extraction_confidence = Column(String, nullable=True)
    extracted_summary = Column(Text, nullable=True)
    doctor_name = Column(String, nullable=True)
    hospital_name = Column(String, nullable=True)
    processed = Column(Boolean, default=False)

    patient = relationship("Patient", back_populates="documents")
    medications = relationship("Medication", back_populates="source_document")


class MedicationReminder(Base):
    __tablename__ = "medication_reminders"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False, index=True)
    medication_id = Column(String, ForeignKey("medications.id"), nullable=True, index=True)
    medicine_name = Column(String, nullable=True)  # used when reminder is created manually
    reminder_time = Column(Time, nullable=False)
    label = Column(String, nullable=True)
    days_of_week = Column(String, nullable=True)  # e.g. "Mon,Tue,Wed"
    dosage = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    last_sent_date = Column(Date, nullable=True)
    created_date = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="reminders")
    medication = relationship("Medication", back_populates="reminders")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False, index=True)
    medication_id = Column(String, ForeignKey("medications.id"), nullable=True)
    reminder_id = Column(String, ForeignKey("medication_reminders.id"), nullable=True)
    message = Column(Text, nullable=False)
    notification_type = Column(String, default="medication")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    is_read = Column(Boolean, default=False)

    patient = relationship("Patient", back_populates="notifications")


class ChatMessage(Base):
    """Persistent user/assistant message for a patient, tied to a ChatSession."""
    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False, index=True)
    session_id = Column(String, ForeignKey("chat_sessions.id"), nullable=False, index=True)
    role = Column(String, nullable=False)  # user / assistant / system
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    patient = relationship("Patient", back_populates="chat_messages")
    session = relationship("ChatSession", back_populates="messages")


class SymptomLog(Base):
    """Patient-reported symptoms extracted from chat."""
    __tablename__ = "symptom_logs"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False, index=True)
    source_message_id = Column(String, ForeignKey("chat_messages.id"), nullable=True)
    symptom_text = Column(Text, nullable=False)
    severity = Column(String, nullable=True)
    duration = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    patient = relationship("Patient", back_populates="symptom_logs")
    chat_message = relationship("ChatMessage")


# Create all tables
Base.metadata.create_all(bind=engine)