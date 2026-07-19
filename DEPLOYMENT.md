# Healthcare Navigation AI Agent - Deployment & Usage Guide

## Project Structure

```
healthcare-navigation-agent/
├── main.py                 # FastAPI application with endpoints
├── agent.py               # Core agent logic with function calling
├── tools.py               # Tool implementations
├── llm.py                 # OpenAI integration
├── models.py              # SQLAlchemy database models
├── seed_data.py           # Sample data generator
├── cli_test.py            # Interactive CLI for testing
├── test_agent.py          # Pytest test suite
├── requirements.txt       # Python dependencies
├── .env.example           # Environment variables template
└── README.md              # Full documentation
```

## Quick Start (Development)

### 1. Setup Environment

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy .env template and add your OpenAI API key
cp .env.example .env
# Edit .env and add: OPENAI_API_KEY=sk-...
```

### 2. Initialize Database

```bash
python seed_data.py
```

Output:
```
✓ Sample data seeded successfully!
✓ Created 2 patients
✓ Patient P001 has:
  - 2 consultations
  - 4 medications (including 1 duplicate: Lisinopril)
  - 3 tests
  - 3 follow-ups (including 1 overdue)

Database: healthcare.db
```

### 3. Start Server

```bash
python main.py
```

Output:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
Healthcare Navigation AI Agent starting up
Available endpoints:
  POST   /agent/chat - Process patient message
  GET    /agent/conversation/{patient_id} - Get conversation history
  DELETE /agent/conversation/{patient_id} - Clear conversation history
  GET    /agent/tools - List available tools
  GET    /health - Health check
```

### 4. Test with CLI

In another terminal:

```bash
python cli_test.py
```

Interactive CLI guide:
```
>>> patient P001          # Select John Smith
>>> chat What medicines am I taking?
>>> history              # View conversation
>>> tools                # See available tools
>>> clear                # Clear history
>>> exit
```

## API Usage Examples

### 1. POST /agent/chat

**Scenario: Patient asks about medications and medication conflicts are detected**

```bash
curl -X POST http://localhost:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "P001",
    "message": "Tell me about my current medications",
    "conversation_history": []
  }'
```

**Expected Response:**
```json
{
  "reply": "⚠️ IMPORTANT: I found a medication issue that needs your doctor's attention immediately.\n\nYou have TWO prescriptions for the same medicine - LISINOPRIL:\n- Lisinopril 10mg (started 90 days ago)\n- Lisinopril 5mg (started 25 days ago)\n\n**PLEASE CALL YOUR DOCTOR TODAY** to clarify which one you should take...",
  "tool_calls_made": [
    {
      "tool": "check_medication_conflicts",
      "arguments": {"patient_id": "P001"},
      "status": "success"
    }
  ],
  "structured_data": {
    "check_medication_conflicts": {
      "patient_id": "P001",
      "has_conflicts": true,
      "conflict_count": 1,
      "conflicts": [...]
    }
  },
  "timestamp": "2024-01-15T10:30:00.123456"
}
```

### 2. POST /agent/chat - With Conversation History

```bash
curl -X POST http://localhost:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "P001",
    "message": "What type of doctor should I see for these symptoms?",
    "conversation_history": [
      {
        "role": "user",
        "content": "I have chest pain and shortness of breath"
      },
      {
        "role": "assistant",
        "content": "Those symptoms require immediate attention from a heart specialist..."
      }
    ]
  }'
```

### 3. GET /agent/conversation/{patient_id}

```bash
curl -X GET http://localhost:8000/agent/conversation/P001
```

**Response:**
```json
{
  "patient_id": "P001",
  "patient_name": "John Smith",
  "message_count": 4,
  "conversation_history": [
    {"role": "user", "content": "What medicines..."},
    {"role": "assistant", "content": "Based on your records..."},
    ...
  ]
}
```

### 4. DELETE /agent/conversation/{patient_id}

```bash
curl -X DELETE http://localhost:8000/agent/conversation/P001
```

**Response:**
```json
{
  "status": "success",
  "message": "Conversation history cleared for patient P001"
}
```

### 5. GET /agent/tools

```bash
curl -X GET http://localhost:8000/agent/tools | python -m json.tool
```

**Response:**
```json
{
  "total_tools": 5,
  "tools": [
    {
      "name": "get_patient_timeline",
      "description": "Get all medical events for a patient in chronological order...",
      "parameters": {
        "type": "object",
        "properties": {
          "patient_id": {
            "type": "string",
            "description": "The unique identifier of the patient"
          }
        },
        "required": ["patient_id"]
      }
    },
    ...
  ]
}
```

## Testing

### Run Unit Tests

```bash
# Install pytest
pip install pytest

# Run tests
pytest test_agent.py -v

# Run specific test
pytest test_agent.py::TestTools::test_recommend_specialist -v

# Run with coverage
pip install pytest-cov
pytest test_agent.py --cov=. --cov-report=html
```

### Manual Testing with cURL

```bash
# Health check
curl http://localhost:8000/health

# Create conversation
PATIENT="P001"

# Message 1
curl -X POST http://localhost:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d "{\"patient_id\": \"$PATIENT\", \"message\": \"Hi, I have questions about my health\"}"

# Message 2 (with history)
curl -X POST http://localhost:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d "{\"patient_id\": \"$PATIENT\", \"message\": \"What medicines am I taking?\", \"conversation_history\": [{\"role\": \"user\", \"content\": \"Hi\"}, {\"role\": \"assistant\", \"content\": \"Hello\"}]}"
```

### Using Python Requests

```python
import requests

# Initialize
BASE_URL = "http://localhost:8000"
patient_id = "P001"

# Send message
response = requests.post(
    f"{BASE_URL}/agent/chat",
    json={
        "patient_id": patient_id,
        "message": "What are my upcoming appointments?",
        "conversation_history": []
    }
)

data = response.json()
print("Agent:", data["reply"])
print("Tools used:", [tc["tool"] for tc in data["tool_calls_made"]])

# Get conversation
response = requests.get(f"{BASE_URL}/agent/conversation/{patient_id}")
history = response.json()["conversation_history"]
print("History length:", len(history))

# Clear conversation
requests.delete(f"{BASE_URL}/agent/conversation/{patient_id}")
```

## Production Deployment

### Docker Deployment

Create `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Initialize database on startup
RUN python seed_data.py || true

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:
```bash
docker build -t healthcare-agent .
docker run -p 8000:8000 -e OPENAI_API_KEY=sk-... healthcare-agent
```

### Docker Compose with PostgreSQL

Create `docker-compose.yml`:
```yaml
version: '3.8'

services:
  agent:
    build: .
    ports:
      - "8000:8000"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - DATABASE_URL=postgresql://user:password@db:5432/healthcare_db
    depends_on:
      - db

  db:
    image: postgres:15-alpine
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=healthcare_db
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

volumes:
  postgres_data:
```

Run:
```bash
OPENAI_API_KEY=sk-... docker-compose up
```

### AWS Lambda + RDS

Key changes needed:
1. Use PostgreSQL instead of SQLite
2. Use Mangum wrapper for ASGI on Lambda
3. Store conversation history in ElastiCache (Redis)
4. Add API Gateway for HTTP routing

### GCP Cloud Run

```bash
# Build and deploy
gcloud run deploy healthcare-agent \
  --source . \
  --set-env-vars OPENAI_API_KEY=sk-... \
  --allow-unauthenticated \
  --platform managed
```

### Azure App Service

```bash
# Create resource group
az group create -n healthcare-rg -l eastus

# Create App Service Plan
az appservice plan create -n healthcare-plan -g healthcare-rg --sku B1

# Create Web App
az webapp create -n healthcare-agent -g healthcare-rg -p healthcare-plan

# Configure environment
az webapp config appsettings set -n healthcare-agent -g healthcare-rg \
  --settings OPENAI_API_KEY=sk-...

# Deploy from local git
git push azure main
```

## Production Considerations

### 1. Conversation Storage

**Current**: In-memory per process (not suitable for multi-worker deployments)

**Production options**:
- Redis: Fast, distributed
- PostgreSQL: Persisted, queryable
- DynamoDB: AWS native, serverless

```python
# Example: Redis backend
import redis

redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)

def get_conversation_history(patient_id: str):
    history = redis_client.get(f"conversation:{patient_id}")
    return json.loads(history) if history else []

def save_conversation_history(patient_id: str, history: list):
    redis_client.setex(
        f"conversation:{patient_id}",
        86400,  # 24 hour expiration
        json.dumps(history)
    )
```

### 2. Rate Limiting

Add rate limiting per patient:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/agent/chat")
@limiter.limit("10/minute")  # 10 requests per minute
async def agent_chat(input_data: MessageInput):
    ...
```

### 3. Audit Logging

Log all interactions for compliance:

```python
import logging

audit_logger = logging.getLogger("audit")

def log_interaction(patient_id: str, message: str, response: str, tools_used: list):
    audit_logger.info(
        f"Patient: {patient_id}, Message: {message}, Tools: {tools_used}",
        extra={"response": response, "timestamp": datetime.utcnow().isoformat()}
    )
```

### 4. Error Monitoring

Integrate with Sentry or similar:

```python
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

sentry_sdk.init(
    dsn="https://your-sentry-dsn",
    integrations=[FastApiIntegration()],
    traces_sample_rate=0.1
)
```

### 5. Caching

Cache tool results to reduce API calls:

```python
from functools import lru_cache
from datetime import datetime, timedelta

CACHE_EXPIRY = timedelta(minutes=30)

@lru_cache(maxsize=1000)
def cached_get_patient_timeline(patient_id: str):
    # Returns (result, expiry_time)
    return (get_patient_timeline(patient_id), datetime.utcnow() + CACHE_EXPIRY)
```

### 6. Model Selection & Cost

**Current**: Uses `gpt-4` (most capable, higher cost)

**Cost optimization**:
```python
# Use gpt-4-turbo for complex queries
# Use gpt-3.5-turbo for simple tool calling

if len(conversation_history) > 10 or has_medication_conflicts:
    model = "gpt-4"
else:
    model = "gpt-3.5-turbo"
```

## Monitoring & Observability

### Key Metrics to Track

1. **Response Time**: How long does agent take to respond?
2. **Tool Usage**: Which tools are called most frequently?
3. **Error Rate**: How many requests fail?
4. **Tool Accuracy**: Are tools returning correct data?
5. **LLM Tokens**: How many tokens are used (cost)?

### Logging Setup

```python
import logging
from logging.handlers import RotatingFileHandler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('agent.log', maxBytes=10485760, backupCount=5),
        logging.StreamHandler()
    ]
)
```

## Security Best Practices

1. **API Key Management**: Use environment variables, never commit keys
2. **Patient Data**: Encrypt sensitive data at rest and in transit
3. **Authentication**: Add JWT or OAuth2 for API access
4. **Rate Limiting**: Prevent abuse and DDoS
5. **Input Validation**: Sanitize all inputs
6. **CORS**: Configure appropriate CORS policies

## Troubleshooting

### Agent Not Responding

```bash
# Check if server is running
curl http://localhost:8000/health

# Check logs
tail -f agent.log
```

### OpenAI API Errors

```python
# Check API key
python -c "import os; print(os.getenv('OPENAI_API_KEY'))"

# Test connection
python -c "from openai import OpenAI; OpenAI().models.list()"
```

### Database Issues

```bash
# Check database file
ls -lh healthcare.db

# Reset database
rm healthcare.db
python seed_data.py
```

## Support & Resources

- OpenAI API Docs: https://platform.openai.com/docs
- FastAPI Docs: https://fastapi.tiangolo.com
- SQLAlchemy Docs: https://docs.sqlalchemy.org
- Function Calling Guide: https://platform.openai.com/docs/guides/function-calling

## License

MIT
