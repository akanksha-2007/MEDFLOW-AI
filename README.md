# Healthcare Navigation AI Agent

A FastAPI-based AI agent that acts as a central conversational interface for healthcare navigation using OpenAI's function calling capabilities. The agent decides when to use tools based on patient queries and maintains conversation context.

## Features

- **Function Calling**: Uses OpenAI's function calling API to intelligently decide which tools to invoke
- **5 Clinical Tools**:
  - `get_patient_timeline`: Retrieve chronological medical history
  - `check_medication_conflicts`: Detect duplicate medications and drug interactions
  - `recommend_specialist`: Suggest appropriate specialists based on symptoms
  - `explain_medical_term`: Provide plain-language medical explanations
  - `get_upcoming_followups`: Track pending appointments and tasks
- **Conversation Memory**: Maintains per-patient conversation history (in-memory, scalable to Redis)
- **Patient-Friendly**: Non-technical language suitable for elderly users
- **Safety-First**: Never diagnoses; always recommends consulting healthcare providers

## Architecture

```
Patient Message
    ↓
[FastAPI Endpoint: /agent/chat]
    ↓
[HealthcareNavigationAgent]
    ├→ LLM with Function Calling (OpenAI)
    │   ├→ Tool: get_patient_timeline
    │   ├→ Tool: check_medication_conflicts
    │   ├→ Tool: recommend_specialist
    │   ├→ Tool: explain_medical_term
    │   └→ Tool: get_upcoming_followups
    ↓
[Natural Language Reply + Structured Data]
```

## Quick Start

### 1. Installation

```bash
# Clone repository (or create project)
cd healthcare-navigation-agent

# Install dependencies
pip install -r requirements.txt

# Create .env file with OpenAI API key
echo "OPENAI_API_KEY=sk-..." > .env
```

### 2. Seed Sample Data

```bash
python seed_data.py
```

This creates:
- 2 test patients (P001: John Smith, P002: Maria Garcia)
- Medical history with consultations, medications, tests, follow-ups
- Sample medication conflicts for testing

### 3. Run the Server

```bash
python main.py
```

Server starts at `http://localhost:8000`

**Available endpoints:**
- `POST /agent/chat` - Process patient message
- `GET /agent/conversation/{patient_id}` - View conversation history
- `DELETE /agent/conversation/{patient_id}` - Clear conversation
- `GET /agent/tools` - View available tools
- `GET /health` - Health check

## API Documentation

### POST /agent/chat

**Request:**
```json
{
  "patient_id": "P001",
  "message": "I'm worried about the chest pain I mentioned last month. What should I do?",
  "conversation_history": [
    {"role": "user", "content": "Hi, I'm John Smith"},
    {"role": "assistant", "content": "Hello John..."}
  ]
}
```

**Response:**
```json
{
  "reply": "I understand your concern about the chest pain. Let me check your medical records to give you better guidance...",
  "tool_calls_made": [
    {
      "tool": "get_patient_timeline",
      "arguments": {"patient_id": "P001"},
      "status": "success"
    },
    {
      "tool": "recommend_specialist",
      "arguments": {"symptoms": "chest pain"},
      "status": "success"
    }
  ],
  "structured_data": {
    "get_patient_timeline": {...},
    "recommend_specialist": {...}
  },
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

### GET /agent/tools

Lists all available tools with schemas:

```json
{
  "total_tools": 5,
  "tools": [
    {
      "name": "get_patient_timeline",
      "description": "Get all medical events for a patient in chronological order...",
      "parameters": {...}
    },
    ...
  ]
}
```

## System Prompt & Agent Behavior

The agent follows strict rules:

✓ **Can do:**
- Navigate patient healthcare journey
- Check medication conflicts
- Recommend specialists
- Explain medical terms in simple language
- Track upcoming appointments

✗ **Cannot do:**
- Diagnose diseases
- Recommend stopping/changing medications
- Provide medical advice (only navigation)
- Bury medication conflicts (must surface clearly)

**Response Style:**
- Short, non-technical language
- Suitable for elderly users
- Always recommend consulting doctor for medical advice
- Clear next steps

### Example: Medication Conflict Detection

If a patient asks "What medicines am I taking?", the agent will:

1. Call `get_patient_timeline` to retrieve medications
2. Call `check_medication_conflicts` to verify for issues
3. If conflicts found, **clearly surface them** in plain language:

```
⚠️ IMPORTANT: I found a medication issue that needs your doctor's attention:

You currently have TWO prescriptions for Lisinopril:
- Lisinopril 10mg (started 90 days ago)
- Lisinopril 5mg (started 25 days ago)

This creates a risk of taking too much of the same medicine. 

PLEASE CALL YOUR DOCTOR TODAY to clarify which one you should take.
```

## Database Schema

### Models (SQLAlchemy)

```
Patient
├── Consultation
│   └── Medication
├── Medication
├── Test
└── FollowUp
```

**Key tables:**
- `patients`: Basic patient info
- `consultations`: Doctor visits
- `medications`: Prescriptions (with date ranges for conflict detection)
- `tests`: Lab/diagnostic tests
- `followups`: Pending actions/appointments

## Tools Reference

### 1. get_patient_timeline

Retrieves all medical events in chronological order.

```python
# Input
get_patient_timeline(patient_id="P001")

# Output
{
  "patient_id": "P001",
  "patient_name": "John Smith",
  "total_events": 10,
  "events": [
    {
      "type": "consultation",
      "date": "2024-01-10T14:30:00",
      "doctor": "Dr. James Wilson",
      "department": "Cardiology",
      "diagnosis": "Hypertension, likely angina"
    },
    {
      "type": "medication",
      "name": "Lisinopril",
      "dosage": "10mg",
      "frequency": "Once daily",
      "start_date": "2023-10-15",
      "status": "active"
    },
    ...
  ]
}
```

### 2. check_medication_conflicts

Detects duplicates, overlapping prescriptions, and drug-drug interactions.

```python
# Input
check_medication_conflicts(patient_id="P001")

# Output
{
  "patient_id": "P001",
  "has_conflicts": true,
  "conflict_count": 2,
  "conflicts": [
    {
      "type": "duplicate_overlap",
      "severity": "HIGH",
      "message": "Duplicate medicine 'Lisinopril' with overlapping prescriptions",
      "medicine1": {...},
      "medicine2": {...}
    },
    {
      "type": "drug_interaction",
      "severity": "HIGH",
      "message": "HIGH - Increased bleeding risk",
      "medicine1": "warfarin",
      "medicine2": "aspirin"
    }
  ]
}
```

### 3. recommend_specialist

Suggests specialists based on symptom keywords.

```python
# Input
recommend_specialist(symptoms="chest pain and shortness of breath")

# Output
{
  "symptom_input": "chest pain and shortness of breath",
  "recommendation_count": 3,
  "recommendations": [
    {
      "specialty": "cardiologist",
      "department": "Cardiology",
      "matched_keywords": ["chest pain"],
      "confidence": 0.8
    },
    {
      "specialty": "pulmonologist",
      "department": "Pulmonology",
      "matched_keywords": ["shortness of breath"],
      "confidence": 0.7
    }
  ]
}
```

### 4. explain_medical_term

Provides plain-language explanations with multi-language support.

```python
# Input
explain_medical_term(term="hypertension", language="english")

# Output
{
  "term": "hypertension",
  "language": "english",
  "explanation": "High blood pressure - the force of blood against artery walls is too strong",
  "source": "healthcare_database",
  "recommendation": "For detailed medical information, consult your healthcare provider."
}
```

Supports: `english`, `spanish`, `french`

### 5. get_upcoming_followups

Tracks pending appointments and tasks with urgency levels.

```python
# Input
get_upcoming_followups(patient_id="P001", days_ahead=30)

# Output
{
  "patient_id": "P001",
  "patient_name": "John Smith",
  "total_pending": 3,
  "overdue_count": 1,
  "upcoming_count": 2,
  "followups": [
    {
      "action": "Reduce Lisinopril dosage - conflicting prescriptions",
      "due_date": "2024-01-13",
      "status": "OVERDUE",
      "priority": "high",
      "days_overdue": 2,
      "urgency": "HIGH"
    },
    {
      "action": "Schedule follow-up cardiology appointment",
      "due_date": "2024-01-22",
      "status": "pending",
      "urgency": "HIGH"
    }
  ]
}
```

## Conversation History

The agent maintains per-patient conversation history (max 20 messages) for context.

### Retrieve History
```bash
curl -X GET http://localhost:8000/agent/conversation/P001
```

### Clear History
```bash
curl -X DELETE http://localhost:8000/agent/conversation/P001
```

## Example Conversation Flow

### Patient Asks About Medical History

**Request:**
```bash
curl -X POST http://localhost:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "P001",
    "message": "What medical issues do I have?"
  }'
```

**Agent decides to use:** `get_patient_timeline`

**Response:**
```json
{
  "reply": "Based on your medical records, you have two main conditions being managed:\n\n1. **Hypertension** (High Blood Pressure) - Your blood pressure is higher than normal. You're taking Lisinopril to help manage this.\n\n2. **Type 2 Diabetes** - Your body has trouble controlling blood sugar. You're taking Metformin to help with this.\n\nYour cardiologist also suspects you might have angina (chest pain from the heart), which is being monitored. You're taking Aspirin as a precaution.\n\nIs there anything specific about these conditions you'd like me to explain?",
  "tool_calls_made": [
    {
      "tool": "get_patient_timeline",
      "arguments": {"patient_id": "P001"},
      "status": "success"
    }
  ],
  "structured_data": { ... }
}
```

### Patient Asks About Medications

**Request:**
```bash
curl -X POST http://localhost:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "P001",
    "message": "Tell me what medicines I should be taking",
    "conversation_history": [...]
  }'
```

**Agent decides to use:** `check_medication_conflicts`

**Response:**
```json
{
  "reply": "⚠️ IMPORTANT: I found a medication issue that needs your doctor's attention immediately.\n\nYou have TWO prescriptions for the same medicine - LISINOPRIL:\n- Lisinopril 10mg (started 90 days ago)\n- Lisinopril 5mg (started 25 days ago)\n\nThis is a duplicate prescription that could be dangerous if you're taking both.\n\n**PLEASE CALL YOUR DOCTOR TODAY** to clarify which one you should take. Don't stop taking either one without talking to them first.\n\nYour other active medicines are:\n- Metformin 500mg (for diabetes)\n- Aspirin 81mg (for heart protection)\n\nThese look fine together, but make sure to resolve the Lisinopril issue urgently.",
  "tool_calls_made": [
    {
      "tool": "check_medication_conflicts",
      "arguments": {"patient_id": "P001"},
      "status": "success"
    }
  ],
  "structured_data": {
    "check_medication_conflicts": {
      "has_conflicts": true,
      "conflict_count": 1,
      ...
    }
  }
}
```

### Patient Describes New Symptoms

**Request:**
```bash
curl -X POST http://localhost:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "P001",
    "message": "I've been having really bad joint pain in my knees and back",
    "conversation_history": [...]
  }'
```

**Agent decides to use:** `recommend_specialist`

**Response:**
```json
{
  "reply": "I'm sorry to hear you're experiencing joint and back pain. Based on your symptoms, here are specialists who can help:\n\n1. **Orthopedist** (Orthopedic Surgeon) - Specializes in bones and joints. They can evaluate your knee and back pain.\n\n2. **Rheumatologist** - If the pain is from inflammation or arthritis.\n\n**Next steps:**\n- Contact your primary care doctor and ask for a referral to an orthopedist\n- Mention when the pain started and what makes it better or worse\n- Your doctor may also want to do X-rays or blood tests\n\nDon't delay seeking care if the pain is severe or prevents you from moving.",
  "tool_calls_made": [
    {
      "tool": "recommend_specialist",
      "arguments": {"symptoms": "joint pain in knees and back"},
      "status": "success"
    }
  ],
  "structured_data": { ... }
}
```

### Patient Asks About Upcoming Tasks

**Request:**
```bash
curl -X POST http://localhost:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "P001",
    "message": "What do I need to do next?",
    "conversation_history": [...]
  }'
```

**Agent decides to use:** `get_upcoming_followups`

**Response:**
```json
{
  "reply": "You have 3 important tasks to complete:\n\n**URGENT (Overdue):**\n- Resolve Lisinopril dosage conflict - This was due 2 days ago. Please call your doctor today!\n\n**HIGH PRIORITY (Due this week):**\n- Schedule a follow-up appointment with your cardiologist (Due: Jan 22)\n- Complete your cholesterol blood test (Due: Jan 18)\n\n**MEDIUM PRIORITY (Next 2 weeks):**\n- Repeat your blood sugar test (Due: Jan 29)\n\nThe medication conflict is the most urgent. Everything else is manageable, but don't delay.",
  "tool_calls_made": [
    {
      "tool": "get_upcoming_followups",
      "arguments": {"patient_id": "P001"},
      "status": "success"
    }
  ],
  "structured_data": { ... }
}
```

## Extending the Agent

### Adding New Tools

1. **Create tool function in `tools.py`:**
```python
def my_new_tool(patient_id: str, db: Session) -> Dict[str, Any]:
    # Implementation
    return result
```

2. **Add to tool schema in `llm.py`:**
```python
{
    "type": "function",
    "function": {
        "name": "my_new_tool",
        "description": "...",
        "parameters": {...}
    }
}
```

3. **Add execution logic in `agent.py`:**
```python
elif tool_name == "my_new_tool":
    return tools.my_new_tool(...)
```

### Customizing System Prompt

Edit `agent.py` `SYSTEM_PROMPT` constant to change agent behavior.

## Production Considerations

- **Conversation Storage**: Switch from in-memory to Redis for distributed deployments
- **LLM Model**: Update `model="gpt-4"` to latest available model
- **Rate Limiting**: Add rate limiting per patient to prevent abuse
- **Audit Logging**: Log all patient interactions for compliance
- **Error Monitoring**: Integrate with Sentry or similar
- **Database**: Use PostgreSQL instead of SQLite
- **Caching**: Cache tool results to reduce API calls
- **Testing**: Add comprehensive unit and integration tests

## Testing

### Manual Testing with cURL

```bash
# Test agent with sample query
curl -X POST http://localhost:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "P001",
    "message": "What are my medications?"
  }' | python -m json.tool

# View conversation
curl http://localhost:8000/agent/conversation/P001 | python -m json.tool

# List tools
curl http://localhost:8000/agent/tools | python -m json.tool

# Health check
curl http://localhost:8000/health
```

### With Python Requests

```python
import requests

response = requests.post(
    "http://localhost:8000/agent/chat",
    json={
        "patient_id": "P001",
        "message": "I have chest pain and shortness of breath"
    }
)

print(response.json())
```

## Files Overview

- **main.py** - FastAPI application and endpoints
- **agent.py** - Core agent logic with function calling
- **tools.py** - Tool implementations using database
- **llm.py** - OpenAI integration and function calling schema
- **models.py** - SQLAlchemy database models
- **seed_data.py** - Sample data generator
- **requirements.txt** - Python dependencies

## Licens

MIT

##Available at your primary URL https://medflow-ai-4.onrender.com
