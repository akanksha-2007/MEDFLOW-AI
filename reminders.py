"""
Medication reminder and notification logic.

- create_reminder / list_reminders / delete_reminder: manage MedicationReminder rows
- check_due_reminders: the scheduler job, run once a minute by main.py's
  APScheduler instance — finds reminders whose time-of-day matches "now"
  and haven't already fired today, and creates a Notification for each.
- list_notifications / mark_notification_read: for the frontend to poll and display
"""

from datetime import datetime, date, time as dt_time
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from models import MedicationReminder, Notification, Medication, Patient, SessionLocal


def create_reminder(
    patient_id: str,
    reminder_time: str,  # "HH:MM", 24-hour, e.g. "08:00" or "21:30"
    db: Session,
    medication_id: Optional[str] = None,
    medicine_name: Optional[str] = None,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new daily reminder at a given time of day.
    Provide EITHER medication_id (for a medicine already on the patient's
    record) OR medicine_name (free text, for a medicine not on file yet —
    e.g. an OTC supplement or a new prescription not uploaded).
    """
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        return {"error": f"Patient {patient_id} not found"}

    resolved_name = None

    if medication_id:
        medication = db.query(Medication).filter(
            Medication.id == medication_id, Medication.patient_id == patient_id
        ).first()
        if not medication:
            return {"error": f"Medication {medication_id} not found for this patient"}
        resolved_name = medication.name
    elif medicine_name and medicine_name.strip():
        resolved_name = medicine_name.strip()
    else:
        return {"error": "Provide either medication_id or medicine_name"}

    try:
        hour, minute = [int(p) for p in reminder_time.strip().split(":")]
        parsed_time = dt_time(hour=hour, minute=minute)
    except (ValueError, AttributeError):
        return {"error": "reminder_time must be in HH:MM 24-hour format, e.g. '08:00' or '21:30'"}

    reminder = MedicationReminder(
        patient_id=patient_id,
        medication_id=medication_id,
        medicine_name=None if medication_id else resolved_name,
        reminder_time=parsed_time,
        label=label,
        is_active=True,
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)

    return {
        "id": reminder.id,
        "patient_id": patient_id,
        "medication_id": medication_id,
        "medicine_name": resolved_name,
        "reminder_time": reminder_time,
        "label": label,
        "is_active": True,
    }


def list_reminders(patient_id: str, db: Session) -> List[Dict[str, Any]]:
    """List all active reminders for a patient, with medicine names resolved
    from either the linked Medication record or the free-text name."""
    reminders = (
        db.query(MedicationReminder)
        .filter(MedicationReminder.patient_id == patient_id, MedicationReminder.is_active == True)
        .all()
    )
    result = []
    for r in reminders:
        if r.medication_id:
            med = db.query(Medication).filter(Medication.id == r.medication_id).first()
            med_name = med.name if med else "Unknown medicine"
        else:
            med_name = r.medicine_name or "Unknown medicine"

        result.append({
            "id": r.id,
            "medication_id": r.medication_id,
            "medication_name": med_name,
            "reminder_time": r.reminder_time.strftime("%H:%M") if r.reminder_time else None,
            "label": r.label,
        })
    return result


def delete_reminder(reminder_id: str, patient_id: str, db: Session) -> Dict[str, Any]:
    """Deactivate (soft-delete) a reminder. Scoped to patient_id so a patient
    can never delete another patient's reminder."""
    reminder = db.query(MedicationReminder).filter(
        MedicationReminder.id == reminder_id, MedicationReminder.patient_id == patient_id
    ).first()
    if not reminder:
        return {"error": "Reminder not found"}

    reminder.is_active = False
    db.commit()
    return {"status": "deleted", "id": reminder_id}


def list_notifications(patient_id: str, db: Session, unread_only: bool = False) -> List[Dict[str, Any]]:
    """List notifications for a patient, most recent first."""
    query = db.query(Notification).filter(Notification.patient_id == patient_id)
    if unread_only:
        query = query.filter(Notification.is_read == False)

    notifications = query.order_by(Notification.created_at.desc()).limit(50).all()
    return [
        {
            "id": n.id,
            "message": n.message,
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "is_read": n.is_read,
        }
        for n in notifications
    ]


def mark_notification_read(notification_id: str, patient_id: str, db: Session) -> Dict[str, Any]:
    """Mark a single notification as read. Scoped to patient_id for safety."""
    notification = db.query(Notification).filter(
        Notification.id == notification_id, Notification.patient_id == patient_id
    ).first()
    if not notification:
        return {"error": "Notification not found"}

    notification.is_read = True
    db.commit()
    return {"status": "read", "id": notification_id}


def check_due_reminders() -> int:
    """
    The scheduler job. Runs once a minute (see main.py startup).
    Opens its own DB session (scheduled jobs run outside any request, so they
    can't use FastAPI's per-request `get_db` dependency).

    For every active reminder whose reminder_time's hour+minute matches the
    current server time, and that hasn't already fired today, creates a
    Notification and stamps last_sent_date so it won't fire again today.

    Returns the number of notifications created (useful for logging/tests).
    """
    db = SessionLocal()
    created_count = 0
    try:
        now = datetime.now()
        today = date.today()

        due_reminders = (
            db.query(MedicationReminder)
            .filter(MedicationReminder.is_active == True)
            .all()
        )

        for reminder in due_reminders:
            if reminder.reminder_time is None:
                continue

            # Already fired today — skip.
            if reminder.last_sent_date == today:
                continue

            # Match on hour+minute (job runs every 60s, so this window is safe).
            if reminder.reminder_time.hour == now.hour and reminder.reminder_time.minute == now.minute:
                if reminder.medication_id:
                    medication = db.query(Medication).filter(Medication.id == reminder.medication_id).first()
                    med_name = medication.name if medication else "your medicine"
                else:
                    med_name = reminder.medicine_name or "your medicine"
                time_str = reminder.reminder_time.strftime("%I:%M %p").lstrip("0")

                message = f"Time to take {med_name} — {time_str}"
                if reminder.label:
                    message += f" ({reminder.label})"

                notification = Notification(
                    patient_id=reminder.patient_id,
                    medication_id=reminder.medication_id,
                    reminder_id=reminder.id,
                    message=message,
                    is_read=False,
                )
                db.add(notification)

                reminder.last_sent_date = today
                created_count += 1

        db.commit()
    finally:
        db.close()

    return created_count