# Healthcare Navigation AI Agent - System Diagram & Flow

## 🏗️ System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         PATIENT CLIENT                          │
│          (Mobile App / Web UI / API Consumer)                   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                    HTTP/REST
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FASTAPI ENDPOINT                             │
│                  POST /agent/chat                               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Input:                                                  │   │
│  │  - patient_id: "P001"                                  │   │
│  │  - message: "What medicines am I on?"                  │   │
│  │  - conversation_history: [...]                         │   │
│  └─────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                    Validate Patient
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              HEALTHCARE NAVIGATION AGENT                        │
│                    (agent.py)                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 1. Retrieve conversation history for patient           │   │
│  │ 2. Add user message to history                         │   │
│  │ 3. Call OpenAI with function calling enabled           │   │
│  └─────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         │ With function schemas
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                OPENAI GPT-4 API (llm.py)                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ LLM Decision: "I need to call these tools:"            │   │
│  │  1. check_medication_conflicts                         │   │
│  │  2. get_patient_timeline                              │   │
│  └─────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
          ┌──────────────┴──────────────┐
          │                             │
    Tool Call #1               Tool Call #2
          │                             │
          ▼                             ▼
┌─────────────────────┐    ┌────────────────────────┐
│  Tool Execution     │    │  Tool Execution        │
│  (tools.py)         │    │  (tools.py)            │
│                     │    │                        │
│ check_medication    │    │ get_patient_timeline   │
│ _conflicts()        │    │ ()                     │
└──────────┬──────────┘    └────────────┬───────────┘
           │                            │
      SQLAlchemy Query            SQLAlchemy Query
           │                            │
           ▼                            ▼
    ┌─────────────────────────────────────────┐
    │  SQLite Database (healthcare.db)        │
    │                                         │
    │  Tables:                                │
    │  ├─ patients                            │
    │  ├─ consultations                       │
    │  ├─ medications                         │
    │  ├─ tests                               │
    │  └─ followups                           │
    └─────────────────────────────────────────┘
           ▲                            ▲
           │                            │
    Results: "Found 2              Results: "Timeline
    Lisinopril prescriptions       with 10 events"
    overlapping"
           │                            │
           └──────────────┬─────────────┘
                         │
                    Format Results
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              FORMAT FOR LLM UNDERSTANDING                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ ⚠️ MEDICATION CONFLICTS FOUND:                          │   │
│  │ - duplicate_overlap: Duplicate medicine 'Lisinopril'... │   │
│  │                                                         │   │
│  │ Medical history (last 10 events):                      │   │
│  │ - CONSULTATION: Hypertension (2024-01-10)            │   │
│  │ - MEDICATION: Lisinopril (active)                     │   │
│  └─────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                    Process with LLM
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                OPENAI GPT-4 API (llm.py)                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Final Response Generation:                              │   │
│  │ "I found an important medication issue. You have TWO    │   │
│  │  Lisinopril prescriptions overlapping. PLEASE CALL      │   │
│  │  YOUR DOCTOR TODAY..."                                  │   │
│  └─────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
              Add to conversation history
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    RESPONSE OBJECT                              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ {                                                       │   │
│  │   "reply": "I found an important medication issue...",  │   │
│  │   "tool_calls_made": [                                 │   │
│  │     {                                                   │   │
│  │       "tool": "check_medication_conflicts",             │   │
│  │       "arguments": {"patient_id": "P001"},              │   │
│  │       "status": "success"                               │   │
│  │     },                                                  │   │
│  │     {                                                   │   │
│  │       "tool": "get_patient_timeline",                   │   │
│  │       "arguments": {"patient_id": "P001"},              │   │
│  │       "status": "success"                               │   │
│  │     }                                                   │   │
│  │   ],                                                    │   │
│  │   "structured_data": {                                 │   │
│  │     "check_medication_conflicts": {...},               │   │
│  │     "get_patient_timeline": {...}                      │   │
│  │   },                                                    │   │
│  │   "timestamp": "2024-01-15T10:30:00Z"                  │   │
│  │ }                                                       │   │
│  └─────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                    HTTP/JSON
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                         PATIENT                                 │
│            Sees natural language response with                  │
│         clear warning about medication conflict                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Function Calling Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│              STEP 1: AGENT RECEIVES MESSAGE                     │
│                                                                 │
│  User: "What medicines am I taking?"                            │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│           STEP 2: RETRIEVE CONVERSATION HISTORY                 │
│                                                                 │
│  History from patient_id "P001":                                │
│  [{"role": "user", "content": "Hi"},                           │
│   {"role": "assistant", "content": "Hello John..."}]           │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│           STEP 3: SEND TO LLM WITH FUNCTION SCHEMAS            │
│                                                                 │
│  Messages:                                                      │
│  [                                                              │
│    {"role": "system", "content": "You are a healthcare..."},   │
│    {"role": "user", "content": "Hi"},                          │
│    {"role": "assistant", "content": "Hello..."},               │
│    {"role": "user", "content": "What medicines am I..."}       │
│  ]                                                              │
│                                                                 │
│  Tools:                                                         │
│  [                                                              │
│    {                                                            │
│      "type": "function",                                        │
│      "function": {                                              │
│        "name": "check_medication_conflicts",                    │
│        "description": "Check for medication...",                │
│        "parameters": {...}                                      │
│      }                                                          │
│    },                                                           │
│    ... (4 more tools)                                           │
│  ]                                                              │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                 STEP 4: LLM DECISION POINT                      │
│                                                                 │
│  LLM analyzes: "What medicines am I taking?"                   │
│  LLM decides: "I should call check_medication_conflicts        │
│               to get accurate current medication data"          │
│                                                                 │
│  Return: {                                                      │
│    "finish_reason": "tool_calls",                              │
│    "tool_calls": [                                              │
│      {                                                          │
│        "id": "call_123",                                        │
│        "type": "function",                                      │
│        "function": {                                            │
│          "name": "check_medication_conflicts",                  │
│          "arguments": "{\"patient_id\": \"P001\"}"               │
│        }                                                        │
│      }                                                          │
│    ]                                                            │
│  }                                                              │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              STEP 5: AGENT EXECUTES TOOL                        │
│                                                                 │
│  Tool: check_medication_conflicts                              │
│  Patient ID: P001                                              │
│                                                                 │
│  Result: {                                                      │
│    "has_conflicts": true,                                       │
│    "conflicts": [                                               │
│      {                                                          │
│        "type": "duplicate_overlap",                             │
│        "severity": "HIGH",                                      │
│        "message": "Duplicate medicine 'Lisinopril' with...",   │
│        "medicine1": {...},                                      │
│        "medicine2": {...}                                       │
│      }                                                          │
│    ]                                                            │
│  }                                                              │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│         STEP 6: FORMAT RESULT FOR LLM UNDERSTANDING            │
│                                                                 │
│  Plain text format that LLM can easily understand:              │
│                                                                 │
│  "MEDICATION CONFLICTS FOUND:                                  │
│   - duplicate_overlap: Duplicate medicine 'Lisinopril' with     │
│     overlapping prescriptions (Severity: HIGH)"                 │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│         STEP 7: SEND RESULT BACK TO LLM                        │
│                                                                 │
│  Messages: [                                                    │
│    {"role": "system", "content": "You are a healthcare..."},   │
│    {"role": "user", "content": "Hi"},                          │
│    {"role": "assistant", "content": "Hello..."},               │
│    {"role": "user", "content": "What medicines..."},           │
│    {"role": "assistant", "content": "...", "tool_calls": [...]},│
│    {"role": "user", "content": "Tool result: MEDICATION..."}   │
│  ]                                                              │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│        STEP 8: LLM GENERATES FINAL RESPONSE                    │
│                                                                 │
│  LLM with context of tool results generates:                   │
│                                                                 │
│  "⚠️ IMPORTANT: I found a medication issue that needs your     │
│   doctor's attention immediately.                              │
│                                                                 │
│   You have TWO prescriptions for the same medicine -            │
│   LISINOPRIL:                                                   │
│   - Lisinopril 10mg (started 90 days ago)                      │
│   - Lisinopril 5mg (started 25 days ago)                       │
│                                                                 │
│   This creates a risk of taking too much of the same medicine. │
│                                                                 │
│   PLEASE CALL YOUR DOCTOR TODAY to clarify which one you       │
│   should take."                                                 │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              STEP 9: RETURN TO PATIENT                          │
│                                                                 │
│  Response: {                                                    │
│    "reply": "⚠️ IMPORTANT: I found a medication issue...",     │
│    "tool_calls_made": [{                                        │
│      "tool": "check_medication_conflicts",                      │
│      "arguments": {"patient_id": "P001"},                       │
│      "status": "success"                                        │
│    }],                                                          │
│    "structured_data": {...},                                    │
│    "timestamp": "2024-01-15T10:30:00Z"                          │
│  }                                                              │
│                                                                 │
│  Patient sees: Clear warning about medication conflict!        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🗂️ Database Schema Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                          PATIENTS                               │
├────────────────────────────────────────────────────────────────┤
│ id (PK): String                    "P001"                       │
│ name: String                       "John Smith"                 │
│ age: Integer                       65                           │
│ date_of_birth: DateTime            1959-03-15                   │
│ gender: String                     "Male"                       │
│ phone: String                      "555-0101"                   │
│ email: String                      "john@example.com"           │
└────────────────────────────────────────────────────────────────┘
         │ 1:N                │ 1:N              │ 1:N
         │                    │                  │
         ▼                    ▼                  ▼
┌─────────────────┐  ┌──────────────────┐  ┌──────────────┐
│ CONSULTATIONS   │  │  MEDICATIONS     │  │   TESTS      │
├─────────────────┤  ├──────────────────┤  ├──────────────┤
│ id (PK)         │  │ id (PK)          │  │ id (PK)      │
│ patient_id (FK) │  │ patient_id (FK)  │  │ patient_id   │
│ date            │  │ consultation_id  │  │ test_name    │
│ doctor_name     │  │ name             │  │ ordered_date │
│ department      │  │ dosage           │  │ completed... │
│ chief_complaint │  │ frequency        │  │ result_...   │
│ diagnosis       │  │ start_date       │  │ reference... │
│ treatment_plan  │  │ end_date         │  └──────────────┘
│ notes           │  │ indication       │
└─────────────────┘  │ notes            │
         │           └──────────────────┘
         │                    │
         │                    │
         └────────┬───────────┘
                  │
                  ▼
         ┌──────────────────┐
         │   FOLLOWUPS      │
         ├──────────────────┤
         │ id (PK)          │
         │ patient_id (FK)  │
         │ due_date         │
         │ action           │
         │ status           │
         │ priority         │
         │ created_date     │
         └──────────────────┘
```

---

## 🔌 API Endpoint Flow

```
┌──────────────────────────────────────────────────────────────────┐
│              POST /agent/chat                                    │
│  (Main conversational endpoint)                                  │
└──────────────────────────────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
┌──────────────────┐ ┌──────────────┐ ┌──────────────────────┐
│ /conversation    │ │ /tools       │ │ /health              │
│ GET/DELETE       │ │ GET          │ │ GET                  │
│                  │ │              │ │                      │
│ View/clear       │ │ List tools & │ │ Server status        │
│ history          │ │ schemas      │ │                      │
└──────────────────┘ └──────────────┘ └──────────────────────┘
```

---

## 🎯 Tool Selection Logic

```
User Message: "What medicines am I taking?"
        │
        ▼
LLM receives message with 5 tool options:
        │
        ├─ get_patient_timeline
        ├─ check_medication_conflicts ◄─ LLM selects this
        ├─ recommend_specialist
        ├─ explain_medical_term
        └─ get_upcoming_followups
        │
        ▼
LLM reasoning: "User is asking about current medicines.
               I should check medication_conflicts to get
               accurate, current medication data with any
               safety issues flagged."
        │
        ▼
Tool executed: check_medication_conflicts(patient_id="P001")
        │
        ▼
Database returns medication data with conflict detection
        │
        ▼
Result formatted: "You're on Lisinopril, Metformin, Aspirin.
                   WARNING: Duplicate Lisinopril prescriptions
                   detected!"
        │
        ▼
LLM generates final response with conflict warning
```

---

## 🌊 Message Flow Through System

```
  PATIENT                    AGENT              LLM          DATABASE
     │                         │                 │                │
     │────Message────────────→ │                 │                │
     │   "What meds?"          │                 │                │
     │                         │                 │                │
     │                         │──Check history→ │                │
     │                         │ (in memory)     │                │
     │                         │←─History────    │                │
     │                         │                 │                │
     │                         │──Tools schema──→ │                │
     │                         │   (5 tools)     │                │
     │                         │                 │                │
     │                         │←─Decision────── │                │
     │                         │ (call tool #2)  │                │
     │                         │                 │                │
     │                         │──Execute tool──────────Query────→ │
     │                         │                 │    Patient P001 │
     │                         │                 │                │
     │                         │                 │←─Medications── │
     │                         │                 │   (4 meds)     │
     │                         │                 │                │
     │                         │   Format & analyze               │
     │                         │   (2 Lisinopril!)                │
     │                         │                 │                │
     │                         │──Tool result──→ │                │
     │                         │ (medication     │                │
     │                         │  conflicts)     │                │
     │                         │                 │                │
     │                         │←─Final response│                 │
     │                         │ (with context)  │                │
     │                         │                 │                │
     │←──Natural language reply │                 │                │
     │  (with warning!)        │                 │                │
     │                         │                 │                │
```

---

## 📊 Data Flow for Medication Conflict Detection

```
QUERY: "What medicines am I on?"
            │
            ▼
    Agent receives message
            │
            ▼
    LLM decides: "Need check_medication_conflicts"
            │
            ▼
    Database query:
    ┌────────────────────────────────────────┐
    │ SELECT * FROM medications              │
    │ WHERE patient_id = 'P001'              │
    │ ORDER BY start_date DESC               │
    └────────────────────────────────────────┘
            │
            ▼
    Results from database:
    ┌────────────────────────────────────────┐
    │ 1. Lisinopril 10mg (started 90d ago)   │
    │ 2. Metformin 500mg (started 180d ago)  │
    │ 3. Aspirin 81mg (started 25d ago)      │
    │ 4. Lisinopril 5mg (started 20d ago) ◄─ DUPLICATE!
    └────────────────────────────────────────┘
            │
            ▼
    Tool logic checks:
    - Are any names identical? YES (Lisinopril)
    - Do date ranges overlap? YES (both active)
    - Any known interactions? Check warfarin/aspirin NO
            │
            ▼
    Tool returns:
    ┌────────────────────────────────────────┐
    │ has_conflicts: true                    │
    │ conflict_count: 1                      │
    │ conflicts: [                           │
    │   {                                    │
    │     type: "duplicate_overlap"          │
    │     severity: "HIGH"                   │
    │     message: "Duplicate Lisinopril..." │
    │   }                                    │
    │ ]                                      │
    └────────────────────────────────────────┘
            │
            ▼
    Format for patient:
    ┌────────────────────────────────────────┐
    │ ⚠️ MEDICATION CONFLICT FOUND:          │
    │                                        │
    │ You have TWO Lisinopril prescriptions: │
    │ • 10mg (from Dr. Wilson)               │
    │ • 5mg (from Dr. Johnson)               │
    │                                        │
    │ This is dangerous if you take both.    │
    │ Call your doctor TODAY!                │
    └────────────────────────────────────────┘
            │
            ▼
    Return to patient with clear warning
```

---

**All diagrams and flows are accurate representations of the system architecture and data flow.**
