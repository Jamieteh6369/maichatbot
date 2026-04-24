import os
import uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from dotenv import load_dotenv
from pydantic import BaseModel
from huggingface_hub import InferenceClient
from database import SessionLocal, ChatSession, Message, init_db

load_dotenv()

hf_client = InferenceClient(api_key=os.getenv("HF_API_KEY"))

app = FastAPI()
init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CORS_HEADERS = {"Access-Control-Allow-Origin": "*"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if code == 429:
        return JSONResponse(
            status_code=429,
            content={"detail": "Quota exceeded. Try again later or enable billing."},
            headers=CORS_HEADERS,
        )
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
        headers=CORS_HEADERS,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=CORS_HEADERS,
    )


class PromptRequest(BaseModel):
    prompt: str
    session_id: str


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.post("/sessions")
def create_session():
    db = SessionLocal()
    try:
        session = ChatSession(id=str(uuid.uuid4()), title="New Chat")
        db.add(session)
        db.commit()
        db.refresh(session)
        return {"id": session.id, "title": session.title, "created_at": session.created_at}
    finally:
        db.close()


@app.get("/sessions")
def get_sessions():
    db = SessionLocal()
    try:
        sessions = db.query(ChatSession).order_by(ChatSession.created_at.desc()).all()
        return [{"id": s.id, "title": s.title, "created_at": s.created_at} for s in sessions]
    finally:
        db.close()


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    db = SessionLocal()
    try:
        session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        db.delete(session)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.get("/sessions/{session_id}/messages")
def get_messages(session_id: str):
    db = SessionLocal()
    try:
        messages = db.query(Message).filter(Message.session_id == session_id).order_by(Message.created_at).all()
        return [{"role": m.role, "content": m.content} for m in messages]
    finally:
        db.close()


@app.post("/generate")
def generate_text_hf(request: PromptRequest):
    print(f"[REQUEST] session={request.session_id} prompt='{request.prompt[:50]}'")
    if not os.getenv("HF_API_KEY"):
        return {"error": "API key not configured. Check your .env file!"}

    db = SessionLocal()
    try:
        session = db.query(ChatSession).filter(ChatSession.id == request.session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        system = {
            "role": "system",
            "content": (
                "You are a helpful assistant. "
                "Keep responses concise and clear. "
                "Use markdown formatting: bullet points for lists and leave a space for each line of bullet points, "
                "**bold** for key terms, and code blocks for code."
            ),
        }
        history = [system] + [{"role": m.role, "content": m.content} for m in session.messages]
        history.append({"role": "user", "content": request.prompt})

        user_msg = Message(id=str(uuid.uuid4()), session_id=request.session_id, role="user", content=request.prompt)
        db.add(user_msg)

        if session.title == "New Chat":
            session.title = request.prompt[:32]
        db.commit()
    finally:
        db.close()

    def stream():
        full_response = ""
        for chunk in hf_client.chat.completions.create(
            model="Qwen/Qwen2.5-7B-Instruct",
            messages=history,
            max_tokens=1000,
            stream=True,
        ):
            token = chunk.choices[0].delta.content
            if token:
                full_response += token
                yield f"data: {token}\n\n"

        db2 = SessionLocal()
        try:
            assistant_msg = Message(id=str(uuid.uuid4()), session_id=request.session_id, role="assistant", content=full_response)
            db2.add(assistant_msg)
            db2.commit()
        finally:
            db2.close()

        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
