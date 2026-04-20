# LLM Chat Interface

A simple chat application powered by Qwen2.5-7B via Hugging Face, built with FastAPI and React.

## Tech Stack

- **Backend**: FastAPI (Python)
- **Frontend**: React + TypeScript
- **Database**: SQLite via SQLAlchemy
- **LLM**: Qwen/Qwen2.5-7B-Instruct (Hugging Face Inference API)
- **Deployment**: Docker + Docker Compose

## Thought Process & Implementation

### Streaming
Instead of waiting for the full response, the backend streams tokens one by one using FastAPI's `StreamingResponse` with Server-Sent Events (SSE). The frontend reads the stream in real time and appends each token to the chat bubble as it arrives.

### Chat Session Management
Each conversation is stored as a session in SQLite. Every message (user and assistant) is saved to the database. When a new message is sent, the full conversation history is loaded and passed to the LLM so it remembers previous messages.

### LLM Memory
The history is passed as a list of messages to the model on every request:
```
[system, ...previous messages, new user message]
```
This gives the model full context of the conversation.

### Frontend
React handles session switching, message rendering, and SSE stream consumption. Responses are rendered as markdown (bold, bullet points, code blocks) using `react-markdown`.

## Running Locally

```bash
# Backend
cd backend
fastapi dev main.py

# Frontend
cd frontend
npm run dev
```

## Running with Docker

```bash
docker-compose up --build
```

Open http://localhost in your browser.

## Test Cases

Tests are written using `pytest` with an in-memory SQLite database so no real database or API calls are made.

| Test | What it verifies |
|------|-----------------|
| `test_create_session` | Session created with correct defaults |
| `test_get_sessions_empty` | Returns empty list when no sessions exist |
| `test_get_sessions_returns_created` | All created sessions are returned |
| `test_delete_session` | Session removed after delete |
| `test_delete_nonexistent_session` | Returns 404 for missing session |
| `test_delete_session_also_deletes_messages` | Cascade delete removes messages |
| `test_get_messages_empty` | Returns empty list for new session |
| `test_get_messages_order` | Messages returned in correct order |
| `test_generate_streams_response` | SSE stream contains tokens and `[DONE]` |
| `test_generate_saves_messages_to_db` | User and assistant messages saved to DB |
| `test_generate_sends_history_to_llm` | Full chat history passed to the model |
| `test_generate_invalid_session` | Returns 404 for unknown session |
| `test_generate_updates_session_title` | Session title updates from first message |

### Testing Methodology
- **Unit tested** each API endpoint independently
- **Mocked** the HuggingFace client to avoid real API calls in tests
- **In-memory SQLite** with `StaticPool` ensures a clean database for every test
- Run tests with: `cd backend && pytest test_main.py -v`
