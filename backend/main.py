from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional
import os, json

from groq import AsyncGroq

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

load_dotenv(os.path.join(BASE_DIR, "..", ".env"))
load_dotenv(os.path.join(BASE_DIR, ".env"))

app = FastAPI(title="AI Chatbot")

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Groq client
client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY", ""))
MODEL = os.getenv("MODEL", "qwen/qwen3.8-27b")

SYSTEM_PROMPT = (
    "You are Spike, a brilliant, warm, and highly capable AI assistant. "
    "You combine the clarity and human touch of Claude with the practical, "
    "direct problem-solving of ChatGPT.\n\n"
    "ResPonse-Length Rule (very important): Match the length of your answer "
    "to the question. For simple factual questions (like prices, times, "
    "definitions, quick facts) give a SHORT, DIRECT answer in 2-4 sentences. "
    "Only give long, structured, multi-section answers when the user asks for "
    "detail, an explanation, or a guide. Never dump long lists or code when "
    "the user only asked a short question.\n"
    "Guidelines:\n"
    "1. Accuracy & honesty: Give accurate information. If it's real-time data "
    "(live prices, weather, news) or you are unsure, say so briefly and cite a "
    "reliable source the user can check. Be honest instead of guessing.\n"
    "2. Lead with the direct answer first, then add only useful detail.\n"
    "3. For code questions, give complete, runnable examples and explain them.\n"
    "4. Adapt tone: casual when casual, professional when technical.\n"
    "5. Use markdown (bold, lists, code blocks) but keep it light — don't "
    "over-format short answers.\n"
    "6. Help with anything: coding, writing, math, planning, analysis, "
    "creativity, general knowledge.\n"
    "7. Always finish your response; never stop halfway."
)


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[Message] = Field(..., min_length=1)
    temperature: Optional[float] = 0.7
    model: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    model: str


@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/health")
async def health():
    ok = bool(os.getenv("GROQ_API_KEY"))
    return {"status": "ok" if ok else "missing_api_key", "model": MODEL}


@app.get("/api/models")
async def models():
    if not os.getenv("GROQ_API_KEY"):
        return {"models": []}
    try:
        data = await client.models.list()
        ids = sorted(
            m.id for m in data.data
            if not any(x in m.id for x in ("whisper", "prompt-guard", "safeguard", "orpheus", "compound", "gpt-oss"))
        )
        return {"models": ids}
    except Exception:
        return {"models": []}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not os.getenv("GROQ_API_KEY"):
        raise HTTPException(
            status_code=500,
            detail=(
                "Groq API key is not set. Copy .env.example to .env "
                "and add your GROQ_API_KEY."
            ),
        )

    model = req.model or MODEL

    history = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in req.messages:
        role = "assistant" if m.role == "bot" else m.role
        if role not in ("user", "assistant"):
            continue
        history.append({"role": role, "content": m.content})

    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=history,
            temperature=req.temperature,
            max_tokens=4000,
        )
        reply = completion.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Groq error: {e}")

    return ChatResponse(reply=reply, model=model)


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    if not os.getenv("GROQ_API_KEY"):
        raise HTTPException(
            status_code=500,
            detail=(
                "Groq API key is not set. Copy .env.example to .env "
                "and add your GROQ_API_KEY."
            ),
        )

    model = req.model or MODEL

    history = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in req.messages:
        role = "assistant" if m.role == "bot" else m.role
        if role not in ("user", "assistant"):
            continue
        history.append({"role": role, "content": m.content})

    async def event_generator():
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=history,
                temperature=req.temperature,
                max_tokens=4000,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield json.dumps({"token": delta}) + "\n"
        except Exception as e:
            yield json.dumps({"error": str(e)}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


# Serve static files last so API routes take precedence
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Simple module-server for `python backend` style runs
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
