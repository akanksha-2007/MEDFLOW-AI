"""
Seed a permanent test patient with a full medical history — consultations,
medications (including an intentional duplicate for testing conflict
detection), tests, and follow-ups — so there's always baseline data
available for testing, even after schema changes/migrations.

Safe to run multiple times: it checks for the patient first and skips
re-creating anything if already present.

Run with:
    python seed_data.py
"""

from datetime import datetime, timedelta
from models import (
    SessionLocal, Patient, Consultation, Medication, Test, FollowUp
)

TEST_PATIENT_ID = "P001"


def seed():
    db = SessionLocal()
    try:
        existing = db.query(Patient).filter(Patient.id == TEST_PATIENT_ID).first()
        if existing:
            print(f"Test patient {TEST_PATIENT_ID} ({existing.name}) already exists — skipping seed.")
            return

        patient = Patient(
            id=TEST_PATIENT_ID,
            name="John Smith",
            age=65,
            date_of_birth=datetime(1961, 3, 12),
            gender="Male",
            phone="555-0101",
            email="john.smith@example.com",
            preferred_language="english",
        )
        db.add(patient)
        db.commit()

        consultation = Consultation(
            patient_id=TEST_PATIENT_ID,
            date=datetime.utcnow() - timedelta(days=30),
            doctor_name="Dr. Patel",
            department="Cardiology",
            chief_complaint="Chest pain, shortness of breath",
            diagnosis="Hypertension, Type 2 Diabetes",
            treatment_plan="Medication management, follow-up in 4 weeks",
            notes="Patient advised to monitor blood pressure daily.",
        )
        db.add(consultation)
        db.commit()

        # Intentional duplicate (same medicine, overlapping dates, two
        # different prescribers) — this is what check_medication_conflicts
        # is designed to catch, kept here on purpose for testing.
        medications = [
            Medication(
                patient_id=TEST_PATIENT_ID,
                consultation_id=consultation.id,
                name="Lisinopril",
                dosage="10mg",
                frequency="Once daily",
                start_date=datetime.utcnow() - timedelta(days=30),
                indication="Hypertension",
                prescribed_by="Dr. Patel",
            ),
            Medication(
                patient_id=TEST_PATIENT_ID,
                consultation_id=consultation.id,
                name="Lisinopril",
                dosage="5mg",
                frequency="Once daily",
                start_date=datetime.utcnow() - timedelta(days=10),
                indication="Hypertension",
                prescribed_by="Dr. Rao",  # different doctor — duplicate!
            ),
            Medication(
                patient_id=TEST_PATIENT_ID,
                consultation_id=consultation.id,
                name="Metformin",
                dosage="500mg",
                frequency="Twice daily",
                start_date=datetime.utcnow() - timedelta(days=30),
                indication="Type 2 Diabetes",
                prescribed_by="Dr. Patel",
            ),
            Medication(
                patient_id=TEST_PATIENT_ID,
                consultation_id=consultation.id,
                name="Aspirin",
                dosage="81mg",
                frequency="Once daily",
                start_date=datetime.utcnow() - timedelta(days=30),
                indication="Cardiovascular protection",
                prescribed_by="Dr. Patel",
            ),
        ]
        db.add_all(medications)

        tests = [
            Test(
                patient_id=TEST_PATIENT_ID,
                test_name="Cardiac Stress Test",
                ordered_date=datetime.utcnow() - timedelta(days=28),
                completed_date=datetime.utcnow() - timedelta(days=25),
                result_status="completed",
                result_value="Normal",
                reference_range="N/A",
            ),
            Test(
                patient_id=TEST_PATIENT_ID,
                test_name="Fasting Blood Sugar",
                ordered_date=datetime.utcnow() - timedelta(days=28),
                completed_date=datetime.utcnow() - timedelta(days=27),
                result_status="abnormal",
                result_value="145 mg/dL",
                reference_range="70-100 mg/dL",
            ),
            Test(
                patient_id=TEST_PATIENT_ID,
                test_name="Cholesterol Panel",
                ordered_date=datetime.utcnow() - timedelta(days=28),
                completed_date=datetime.utcnow() - timedelta(days=27),
                result_status="completed",
                result_value="LDL 110 mg/dL",
                reference_range="<100 mg/dL",
            ),
        ]
        db.add_all(tests)

        followups = [
            FollowUp(
                patient_id=TEST_PATIENT_ID,
                due_date=datetime.utcnow() + timedelta(days=2),
                action="Follow-up cardiology consult",
                status="pending",
                priority="high",
            ),
            FollowUp(
                patient_id=TEST_PATIENT_ID,
                due_date=datetime.utcnow() + timedelta(days=14),
                action="Repeat fasting blood sugar test",
                status="pending",
                priority="medium",
            ),
        ]
        db.add_all(followups)

        db.commit()
        print(f"Seeded test patient {TEST_PATIENT_ID} — John Smith — with full history.")
        print("Includes an intentional duplicate Lisinopril prescription for testing conflict detection.")

    finally:
        db.close()


if __name__ == "__main__":
    seed()