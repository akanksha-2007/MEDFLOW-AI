"""
Integration tests for the healthcare navigation agent.
Run with: pytest test_agent.py
"""

import pytest
import json
from datetime import datetime, timedelta
from models import SessionLocal, Patient, Consultation, Medication, FollowUp, MedicalDocument
from agent import HealthcareNavigationAgent, CONVERSATION_HISTORIES
from sqlalchemy.orm import Session


@pytest.fixture
def db():
    """Provide a database session for tests."""
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture
def agent(db):
    """Provide a healthcare navigation agent."""
    return HealthcareNavigationAgent(db)


@pytest.fixture
def test_patient(db):
    """Create a test patient."""
    patient = Patient(
        id="TEST_P001",
        name="Test Patient",
        age=50,
        date_of_birth=datetime(1974, 1, 1),
        gender="Male",
        phone="555-0001",
        email="test@example.com"
    )
    db.add(patient)
    db.commit()

    yield patient

    # Cleanup — every child table that can reference TEST_P001 must be
    # cleared, not just Medication/Consultation, or leftover rows from
    # one test run will pollute the next run's assertions.
    db.query(Medication).filter(Medication.patient_id == "TEST_P001").delete()
    db.query(Consultation).filter(Consultation.patient_id == "TEST_P001").delete()
    db.query(FollowUp).filter(FollowUp.patient_id == "TEST_P001").delete()
    db.query(MedicalDocument).filter(MedicalDocument.patient_id == "TEST_P001").delete()
    db.query(Patient).filter(Patient.id == "TEST_P001").delete()
    db.commit()


class TestAgent:
    """Test suite for healthcare navigation agent."""

    def test_patient_not_found(self, agent):
        """Test handling of non-existent patient."""
        result = agent.process_message(
            patient_id="NONEXISTENT",
            user_message="Hello"
        )

        assert "error" in result
        assert result["reply"] is not None

    def test_conversation_history_management(self, agent, test_patient):
        """Test conversation history is maintained."""
        patient_id = test_patient.id

        if patient_id in CONVERSATION_HISTORIES:
            del CONVERSATION_HISTORIES[patient_id]

        agent.add_to_history(patient_id, "user", "Hello")
        agent.add_to_history(patient_id, "assistant", "Hi there")

        history = agent.get_conversation_history(patient_id)

        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    def test_history_trimming(self, agent, test_patient):
        """Test that history is trimmed to max length."""
        patient_id = test_patient.id

        if patient_id in CONVERSATION_HISTORIES:
            del CONVERSATION_HISTORIES[patient_id]

        for i in range(30):
            agent.add_to_history(patient_id, "user", f"Message {i}")

        history = agent.get_conversation_history(patient_id)

        from agent import MAX_HISTORY_LENGTH
        assert len(history) <= MAX_HISTORY_LENGTH

    def test_get_conversation_history(self, agent, test_patient):
        """Test retrieving conversation history."""
        patient_id = test_patient.id

        if patient_id in CONVERSATION_HISTORIES:
            del CONVERSATION_HISTORIES[patient_id]

        agent.add_to_history(patient_id, "user", "Test message")

        history = agent.get_conversation_history(patient_id)

        assert len(history) == 1
        assert history[0]["content"] == "Test message"


class TestTools:
    """Test suite for tool execution."""

    def test_get_patient_timeline(self, db, test_patient):
        """Test get_patient_timeline tool."""
        from tools import get_patient_timeline

        consultation = Consultation(
            id="C_TEST_001",
            patient_id=test_patient.id,
            date=datetime.utcnow(),
            doctor_name="Dr. Test",
            department="General",
            chief_complaint="Test",
            diagnosis="Test Condition",
            treatment_plan="Test Plan"
        )
        db.add(consultation)
        db.commit()

        result = get_patient_timeline(test_patient.id, db)

        assert result["patient_id"] == test_patient.id
        assert result["patient_name"] == test_patient.name
        assert len(result["events"]) > 0
        assert result["events"][0]["type"] == "consultation"

    def test_check_medication_conflicts_duplicate(self, db, test_patient):
        """Test check_medication_conflicts tool detects same-medicine duplicates."""
        from tools import check_medication_conflicts

        consultation = Consultation(
            id="C_TEST_002",
            patient_id=test_patient.id,
            date=datetime.utcnow(),
            doctor_name="Dr. Test",
            department="General",
            chief_complaint="Test"
        )
        db.add(consultation)
        db.commit()

        med1 = Medication(
            id="M_TEST_001",
            patient_id=test_patient.id,
            consultation_id=consultation.id,
            name="Test Medicine",
            dosage="10mg",
            frequency="Daily",
            prescribed_by="Dr. A",
            start_date=datetime.utcnow() - timedelta(days=10),
            end_date=None
        )

        med2 = Medication(
            id="M_TEST_002",
            patient_id=test_patient.id,
            consultation_id=consultation.id,
            name="Test Medicine",  # Same name - duplicate
            dosage="5mg",
            frequency="Daily",
            prescribed_by="Dr. B",
            start_date=datetime.utcnow() - timedelta(days=5),
            end_date=None
        )

        db.add_all([med1, med2])
        db.commit()

        result = check_medication_conflicts(test_patient.id, db)

        assert result["has_conflicts"] is True
        assert any(c["type"] == "duplicate" for c in result["conflicts"])

    def test_check_medication_conflicts_cross_provider(self, db, test_patient):
        """Test detection of two DIFFERENT medicines, overlapping dates,
        prescribed by two DIFFERENT doctors — the uncoordinated-care case."""
        from tools import check_medication_conflicts

        med1 = Medication(
            id="M_TEST_003",
            patient_id=test_patient.id,
            name="Amoxicillin",
            dosage="500mg",
            frequency="Twice daily",
            prescribed_by="Dr. A",
            start_date=datetime.utcnow() - timedelta(days=5),
            end_date=None
        )

        med2 = Medication(
            id="M_TEST_004",
            patient_id=test_patient.id,
            name="Ibuprofen",
            dosage="200mg",
            frequency="Once daily",
            prescribed_by="Dr. B",
            start_date=datetime.utcnow() - timedelta(days=3),
            end_date=None
        )

        db.add_all([med1, med2])
        db.commit()

        result = check_medication_conflicts(test_patient.id, db)

        assert result["has_conflicts"] is True
        assert any(c["type"] == "overlapping_prescription" for c in result["conflicts"])

    def test_recommend_specialist(self):
        """Test recommend_specialist tool."""
        from tools import recommend_specialist

        result = recommend_specialist("chest pain and shortness of breath")

        assert "recommendations" in result
        assert len(result["recommendations"]) > 0

        specialties = [r["specialty"] for r in result["recommendations"]]
        assert "cardiologist" in specialties or "pulmonologist" in specialties

    def test_recommend_specialist_no_match(self):
        """Test recommend_specialist with no specific matches."""
        from tools import recommend_specialist

        result = recommend_specialist("xyz abc 123")

        assert "recommendations" in result
        assert len(result["recommendations"]) > 0
        assert result["recommendations"][0]["specialty"] == "general_practitioner"

    def test_explain_medical_term(self):
        """Test explain_medical_term tool."""
        from tools import explain_medical_term

        result = explain_medical_term("hypertension")

        assert result["term"] == "hypertension"
        assert "explanation" in result
        assert len(result["explanation"]) > 0

    def test_explain_medical_term_with_language(self):
        """Test explain_medical_term with Hindi language support."""
        from tools import explain_medical_term

        result = explain_medical_term("diabetes", language="hindi")

        assert result["language"] == "hindi"
        assert "explanation" in result
        assert len(result["explanation"]) > 0

    def test_get_upcoming_followups(self, db, test_patient):
        """Test get_upcoming_followups tool."""
        from tools import get_upcoming_followups

        followup = FollowUp(
            id="F_TEST_001",
            patient_id=test_patient.id,
            due_date=datetime.utcnow() + timedelta(days=7),
            action="Test follow-up",
            status="pending",
            priority="high"
        )
        db.add(followup)
        db.commit()

        result = get_upcoming_followups(test_patient.id, db)

        assert result["patient_id"] == test_patient.id
        assert result["upcoming_count"] >= 1
        assert len(result["followups"]) > 0


class TestAPIEndpoints:
    """Test suite for API endpoints using FastAPI TestClient."""

    @pytest.fixture
    def client(self):
        """Provide FastAPI test client."""
        from fastapi.testclient import TestClient
        from main import app

        return TestClient(app)

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_agent_chat_patient_not_found(self, client):
        """Test chat endpoint with non-existent patient."""
        response = client.post(
            "/agent/chat",
            json={
                "patient_id": "NONEXISTENT",
                "message": "Hello"
            }
        )

        assert response.status_code == 404

    def test_list_tools(self, client):
        """Test tools listing endpoint."""
        response = client.get("/agent/tools")

        assert response.status_code == 200
        data = response.json()
        assert data["total_tools"] == 5
        assert len(data["tools"]) == 5

        tool_names = [t["name"] for t in data["tools"]]
        assert "get_patient_timeline" in tool_names
        assert "check_medication_conflicts" in tool_names
        assert "recommend_specialist" in tool_names
        assert "explain_medical_term" in tool_names
        assert "get_upcoming_followups" in tool_names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])