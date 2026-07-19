# Healthcare Navigation AI Agent - Quick Reference

## 📖 Quick Start (5 minutes)

```bash
# 1. Setup
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your OpenAI API key: OPENAI_API_KEY=sk-...

# 2. Initialize database with sample data
python seed_data.py

# 3. Start server
python main.py
# Server runs at http://localhost:8000

# 4. In another terminal, test with CLI
python cli_test.py

# 5. Or test with curl
curl -X POST http://localhost:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"patient_id":"P001","message":"What medicines am I taking?"}'
```

## 🎯 Core Endpoints

### POST /agent/chat
Process a patient message through the agent with function calling.

**Request:**
```json
{
  "patient_id": "P001",
  "message": "What medicines am I taking?",
  "conversation_history": [optional list of previous messages]
}
```

**Response:**
```json
{
  "reply": "You're taking: Lisinopril, Metformin, Aspirin...",
  "tool_calls_made": [{"tool": "check_medication_conflicts", ...}],
  "structured_data": {...},
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### GET /agent/conversation/{patient_id}
View conversation history for a patient.

### DELETE /agent/conversation/{patient_id}
Clear conversation history for a patient.

### GET /agent/tools
Get documentation for all available tools.

### GET /health
Health check endpoint.

## 🔧 Available Tools

| Tool | Purpose | Triggers On |
|------|---------|-------------|
| `get_patient_timeline` | Get medical history | "Tell me my history", "What happened?" |
| `check_medication_conflicts` | Detect drug conflicts | "What meds am I on?", medication question |
| `recommend_specialist` | Suggest doctor type | "What type of doctor?", symptom description |
| `explain_medical_term` | Plain-language explanation | "What does X mean?" |
| `get_upcoming_followups` | Show pending tasks | "What next?", "Upcoming appointments?" |

## 🧪 Test Patients

**P001 - John Smith** (65M)
- Conditions: Hypertension, Type 2 Diabetes, possible angina
- Medications: Lisinopril (DUPLICATE!), Metformin, Aspirin
- Tests: Stress test, Blood sugar, Cholesterol
- Follow-ups: 3 pending (1 overdue)

**P002 - Maria Garcia** (52F)
- Base patient for additional testing

## 💻 Python API Example

```python
import requests

response = requests.post(
    "http://localhost:8000/agent/chat",
    json={
        "patient_id": "P001",
        "message": "I'm confused about my medications",
        "conversation_history": []
    }
)

data = response.json()
print("Agent:", data["reply"])
print("Tools used:", [tc["tool"] for tc in data["tool_calls_made"]])
```

## 🔍 Understanding Function Calling

**Without function calling (bad):**
```
User → "Tell me my meds" → LLM generates guess → "You probably take..."
                                                   (might be wrong!)
```

**With function calling (good):**
```
User → "Tell me my meds" → LLM decides → Tool: get_patient_timeline
                                        ↓
                                     Database lookup ✓
                                        ↓
                                     "You take: X, Y, Z..."
```

## 🚨 Medication Conflict Response

If agent finds conflicts, it **MUST** surface them clearly:

```
⚠️ IMPORTANT: Medication conflict detected!

You have TWO prescriptions for Lisinopril:
- Lisinopril 10mg (from Dr. Wilson)
- Lisinopril 5mg (from Dr. Johnson)

This is a SAFETY ISSUE.

ACTION REQUIRED: Call your doctor TODAY to clarify which one to take.
```

## 🛑 What the Agent CANNOT Do

- ❌ Diagnose diseases ("You have X")
- ❌ Prescribe medications ("Take Y")
- ❌ Recommend stopping meds ("Don't take Z")
- ❌ Provide medical advice ("Eat less salt")
- ❌ Emergency care ("Call 911" only if patient tells you)

## ✅ What the Agent CAN Do

- ✅ Navigate care ("A cardiologist helps with heart issues")
- ✅ Surface conflicts ("Two meds for same condition detected")
- ✅ Explain terms ("Hypertension means high blood pressure")
- ✅ Track appointments ("You have a cardiology visit on Jan 20")
- ✅ Recommend specialists ("For chest pain, see a cardiologist")

## 📊 Database Models

```python
Patient
  ├─ Consultation (date, doctor, diagnosis)
  ├─ Medication (name, dosage, date range)
  ├─ Test (test name, result, status)
  └─ FollowUp (action, due date, priority)
```

## 🔐 Agent System Prompt

The agent follows these core rules (in the system prompt):

1. **Never diagnose** - Only help navigate
2. **Always surface conflicts** - Don't bury medication issues
3. **Use simple language** - For elderly patients
4. **Recommend consulting doctor** - For medical advice
5. **Be empathetic** - Acknowledge patient concerns

## 📁 File Guide

| File | Purpose | Lines |
|------|---------|-------|
| main.py | FastAPI endpoints | 350 |
| agent.py | Core agent logic | 350 |
| tools.py | Tool implementations | 300 |
| llm.py | OpenAI integration | 150 |
| models.py | Database schema | 150 |
| seed_data.py | Test data | 200 |
| cli_test.py | Interactive testing | 350 |
| test_agent.py | Unit tests | 400 |
| README.md | Full documentation | - |
| DEPLOYMENT.md | Production guide | - |

## 🐛 Troubleshooting

**Server won't start:**
```bash
# Check if port 8000 is free
lsof -i :8000  # macOS/Linux
netstat -ano | findstr :8000  # Windows

# Kill process using port
kill -9 <PID>  # macOS/Linux
```

**OpenAI API errors:**
```bash
# Check API key
echo $OPENAI_API_KEY

# Verify format
python -c "import os; print(len(os.getenv('OPENAI_API_KEY','')))"  # Should be ~48
```

**Database errors:**
```bash
# Recreate database
rm healthcare.db
python seed_data.py
```

**Import errors:**
```bash
# Reinstall dependencies
pip install --upgrade -r requirements.txt
```

## 🚀 Deployment Options

| Platform | Command | Notes |
|----------|---------|-------|
| Local | `python main.py` | Development |
| Docker | `docker build -t agent . && docker run -p 8000:8000 agent` | Production |
| Cloud Run | `gcloud run deploy healthcare-agent --source .` | Fully managed |
| Lambda | Requires Mangum wrapper | Serverless |
| App Service | `az webapp create ... && git push azure main` | Azure |

## 📈 Monitoring What to Track

1. **Response Time** - How long agent takes to respond
2. **Tools Used** - Which tools are called most
3. **Error Rate** - Failed requests
4. **LLM Tokens** - Cost of API calls
5. **Conflicts Found** - Medication safety issues

## 🎓 Key Concepts

**Function Calling**: 
- Tool schemas tell LLM what functions are available
- LLM decides which functions to call based on user message
- No hallucinations about tool behavior

**Agent Pattern**:
- Receives user message
- Decides what tool(s) to use
- Executes tools
- Formats results
- Generates final response

**Conversation Memory**:
- Keeps last 20 messages per patient
- Provides context to LLM
- Can be stored in Redis for scale

## 🎯 Common Queries & Expected Behavior

| Query | Tools Called | Behavior |
|-------|--------------|----------|
| "What meds am I on?" | `check_medication_conflicts` | Surfaces any conflicts first |
| "What happened in my last visit?" | `get_patient_timeline` | Shows consultations |
| "I have chest pain" | `recommend_specialist` | Suggests cardiologist |
| "What's diabetes?" | `explain_medical_term` | Plain-language explanation |
| "What do I need to do?" | `get_upcoming_followups` | Lists tasks and appointments |

## 💡 Pro Tips

1. **Use conversation history** - Pass previous messages for context
2. **Check tools endpoint** - See all available tools and schemas
3. **Monitor conflicts** - Proactively check medications for new patients
4. **Clear history** - Reset conversation if needed
5. **Check logs** - Review agent.log for debugging

## 🔗 Related Files

- **Full API Docs**: See README.md
- **Deployment Guide**: See DEPLOYMENT.md  
- **Architecture Details**: See SUMMARY.md
- **Examples**: See cli_test.py

## 📞 Support Resources

- FastAPI: https://fastapi.tiangolo.com
- OpenAI Function Calling: https://platform.openai.com/docs/guides/function-calling
- SQLAlchemy: https://docs.sqlalchemy.org
- This project: See README.md and DEPLOYMENT.md

---

**Version**: 1.0.0  
**Last Updated**: January 2024  
**Status**: Production Ready ✅
