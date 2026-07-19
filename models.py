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

    # Optional location for OpenStreetMap nearby-doctor searches.
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
    chat_messages = relationship("ChatMessage", back_populates="patient", cascade="all, delete-orphan")
    symptom_logs = relationship("SymptomLog", back_populates="patient", cascade="all, delete-orphan")


class Consultation(Base):
    __tablename__ = "consultations"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"))
    date = Column(DateTime, index=True)
    doctor_name = Column(String)
    department = Column(String)
    chief_complaint = Column(Text)
    diagnosis = Column(Text)
    treatment_plan = Column(Text)
    notes = Column(Text)

    patient = relationship("Patient", back_populates="consultations")
    medications = relationship("Medication", back_populates="consultation")


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


class Test(Base):
    __tablename__ = "tests"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"))
    test_name = Column(String, index=True)
    ordered_date = Column(DateTime)
    scheduled_date = Column(DateTime, nullable=True)
    completed_date = Column(DateTime, nullable=True)
    result_status = Column(String)
    result_value = Column(String)
    reference_range = Column(String)
    notes = Column(Text)

    patient = relationship("Patient", back_populates="tests")


class FollowUp(Base):
    __tablename__ = "followups"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"))
    due_date = Column(DateTime, index=True)
    action = Column(String)
    status = Column(String)
    priority = Column(String)
    created_date = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="followups")


class MedicalDocument(Base):
    __tablename__ = "medical_documents"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"))
    file_url = Column(String)
    document_type = Column(Enum(DocumentType))
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    ocr_extracted_text = Column(Text, nullable=True)
    extraction_confidence = Column(String, nullable=True)

    patient = relationship("Patient", back_populates="documents")


class MedicationReminder(Base):
    __tablename__ = "medication_reminders"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), index=True)
    medication_id = Column(String, ForeignKey("medications.id"), nullable=True, index=True)
    medicine_name = Column(String, nullable=True)
    reminder_time = Column(Time)
    label = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    last_sent_date = Column(Date, nullable=True)
    created_date = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="reminders")
    medication = relationship("Medication", back_populates="reminders")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), index=True)
    medication_id = Column(String, ForeignKey("medications.id"), nullable=True)
    reminder_id = Column(String, ForeignKey("medication_reminders.id"), nullable=True)
    message = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    is_read = Column(Boolean, default=False)

    patient = relationship("Patient", back_populates="notifications")


class ChatMessage(Base):
    """Persistent user/assistant message for a patient."""
    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), index=True, nullable=False)
    role = Column(String, nullable=False)  # user or assistant
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)

    patient = relationship("Patient", back_populates="chat_messages")


class SymptomLog(Base):
    """A patient-reported problem/symptom extracted from a chat message."""
    __tablename__ = "symptom_logs"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    patient_id = Column(String, ForeignKey("patients.id"), index=True, nullable=False)
    symptom_text = Column(Text, nullable=False)
    severity = Column(String, nullable=True)
    duration = Column(String, nullable=True)
    source_message_id = Column(String, ForeignKey("chat_messages.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)

    patient = relationship("Patient", back_populates="symptom_logs")


# Creates missing tables only. Existing columns are added through migrate_db.py.
Base.metadata.create_all(bind=engine)
