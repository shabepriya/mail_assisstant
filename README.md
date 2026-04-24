# AI Email Assistant

FastAPI service: fetches emails (or mocks), builds a safe context, calls OpenAI, returns chat answers.

## Setup

```bash
cd mail_assistant
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy .env.example .env
# Set OPENAI_API_KEY in .env for real AI; MOCK_EMAILS=true uses fixtures
```

## Run

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/ for the chat UI. API: `POST /ai/chat`, `GET /health`.

**Use `--workers 1` in production** so in-memory email cache stays consistent.

## Docker

```bash
docker build -t mail-assistant .
docker run -p 8000:8000 --env-file .env mail-assistant
```

## Tests

```bash
pytest
```
