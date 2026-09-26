"""FastAPI backend for ChatWell's server-rendered pages and chat endpoint."""

from contextlib import asynccontextmanager, closing
from datetime import datetime
from functools import lru_cache
import logging
from operator import itemgetter
import os
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from groq import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)
from langchain_groq import ChatGroq
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.environ.get("CHATWELL_DB_PATH", BASE_DIR / "therapist.db"))
KNOWLEDGE_PATH = BASE_DIR / "knowledge.txt"
CHROMA_PATH = BASE_DIR / "chroma_db"
MODEL_ID = "openai/gpt-oss-120b"
logger = logging.getLogger(__name__)


class MissingGroqKeyError(RuntimeError):
    """The Groq API key has not been configured for this process."""


def init_db() -> None:
    with closing(sqlite3.connect(DATABASE_PATH)) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS moods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mood TEXT NOT NULL,
                note TEXT,
                date TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        conn.commit()


def save_message(session_id: str, role: str, content: str) -> None:
    try:
        with closing(sqlite3.connect(DATABASE_PATH)) as conn:
            conn.execute(
                "INSERT INTO chat_history (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )
            conn.commit()
    except sqlite3.Error as exc:
        logger.error("Could not save a chat message (%s)", type(exc).__name__)


def recent_chat_history(session_id: str, limit: int = 8) -> list[BaseMessage]:
    """Return a bounded conversation for this browser session only."""
    with closing(sqlite3.connect(DATABASE_PATH)) as conn:
        rows = conn.execute(
            "SELECT role, content FROM chat_history WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [
        HumanMessage(content=content) if role == "User" else AIMessage(content=content)
        for role, content in reversed(rows)
    ]


@lru_cache(maxsize=1)
def get_groq_llm() -> ChatGroq:
    """Create the hosted chat model only when the first chat is requested."""
    load_dotenv(BASE_DIR / ".env", override=False)
    if not os.environ.get("GROQ_API_KEY"):
        raise MissingGroqKeyError("GROQ_API_KEY is not set")
    model_id = os.environ.get("GROQ_MODEL", MODEL_ID)
    return ChatGroq(
        model=model_id,
        temperature=0.6,
        max_tokens=1024 if model_id.startswith("openai/gpt-oss-") else 512,
        reasoning_effort="none" if model_id.startswith("qwen/") else "low",
        reasoning_format="hidden" if model_id.startswith("qwen/") else None,
        model_kwargs=(
            {"include_reasoning": False}
            if model_id.startswith("openai/gpt-oss-")
            else {}
        ),
        timeout=90,
        max_retries=0,
    )


@lru_cache(maxsize=1)
def get_rag_chain():
    """Build the local retriever and Groq answer pipeline on first chat."""
    llm = get_groq_llm()
    from langchain_chroma import Chroma
    from langchain_core.documents import Document
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    embedding_function = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )
    vector_db = Chroma(
        persist_directory=str(CHROMA_PATH), embedding_function=embedding_function
    )
    if not vector_db.get(limit=1)["ids"]:
        docs = [Document(page_content=KNOWLEDGE_PATH.read_text(encoding="utf-8"))]
        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        vector_db.add_documents(splitter.split_documents(docs))

    retriever = vector_db.as_retriever(search_kwargs={"k": 3})

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You are ChatWell, a supportive coping-skills prototype, not a clinician.
Use the conversation history to understand references to earlier advice and its outcome.
Answer the latest message directly. If the user already tried a suggestion or says it did not help, acknowledge that and do not repeat it. Offer a different option only if useful; do not promise immediate relief.
Do not diagnose or claim that a feeling proves a mental health condition. If symptoms persist or interfere with daily life, gently suggest talking with a qualified health professional.
Keep your response under 140 words and finish every instruction in a complete sentence.""",
            ),
            MessagesPlaceholder("history"),
            (
                "human",
                "Relevant coping guidance:\n{context}\n\nCurrent message:\n{input}",
            ),
        ]
    )

    def format_docs(docs):
        return "\n\n".join(doc.page_content for doc in docs)

    return (
        {
            "context": itemgetter("input") | retriever | format_docs,
            "history": itemgetter("history"),
            "input": itemgetter("input"),
        }
        | prompt
        | llm
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="ChatWell", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class ChatInput(BaseModel):
    symptoms: str = Field(min_length=1, max_length=4000)
    duration: str = ""
    age: str = ""
    sex: str = ""
    session_id: str = Field(
        default_factory=lambda: uuid4().hex,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


def groq_rate_limit_response(exc: RateLimitError) -> JSONResponse:
    """Explain the quota Groq named without exposing its raw error details."""
    body = exc.body if isinstance(exc.body, dict) else {}
    detail = body.get("error", body)
    message = detail.get("message", "") if isinstance(detail, dict) else ""
    description = str(message).lower()
    limits = (
        (("output tokens per minute", "otpm"), "output tokens per minute"),
        (("input tokens per minute", "itpm"), "input tokens per minute"),
        (("tokens per minute", "tpm"), "tokens per minute"),
        (("tokens per day", "tpd"), "tokens per day"),
        (("requests per minute", "rpm"), "requests per minute"),
        (("requests per day", "rpd"), "requests per day"),
    )
    name = next((label for terms, label in limits if any(term in description for term in terms)), None)
    error = f"Groq's {name} limit was reached." if name else "Groq's rate limit was reached."

    retry_after = exc.response.headers.get("retry-after", "").strip()
    headers = {}
    if retry_after.isdecimal() and 0 < int(retry_after) <= 86400:
        seconds = int(retry_after)
        wait = f"{seconds} seconds" if seconds < 120 else f"{(seconds + 59) // 60} minutes"
        error += f" Try again in about {wait}."
        headers["Retry-After"] = retry_after
    else:
        error += " Please try again later."
    return JSONResponse(status_code=429, content={"error": error}, headers=headers)


@app.get("/", response_class=HTMLResponse, name="index")
def index(request: Request):
    with closing(sqlite3.connect(DATABASE_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        moods = conn.execute("SELECT * FROM moods ORDER BY id DESC").fetchall()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "moods": moods,
            "css_version": (BASE_DIR / "static" / "compiled-tailwind.css").stat().st_mtime_ns,
            "script_version": (BASE_DIR / "static" / "script.js").stat().st_mtime_ns,
        },
    )


@app.post("/add_mood", name="add_mood")
def add_mood(mood: str | None = Form(None), note: str | None = Form(None)):
    if mood:
        with closing(sqlite3.connect(DATABASE_PATH)) as conn:
            conn.execute(
                "INSERT INTO moods (mood, note, date) VALUES (?, ?, ?)",
                (mood, note, datetime.now().strftime("%Y-%m-%d %H:%M")),
            )
            conn.commit()
    return RedirectResponse(url="/#moods", status_code=303)


@app.get("/chat", name="chatbot")
def chatbot():
    """Preserve old chat links while serving one unified page."""
    return RedirectResponse(url="/#chat", status_code=303)


@app.post("/chat", name="chat")
def chat(data: ChatInput):
    context = []
    if data.age.strip():
        context.append(f"Client is {data.age} years old")
    if data.sex.strip():
        context.append(data.sex)
    if data.duration.strip():
        context.append(f"duration: {data.duration}")
    user_input = data.symptoms
    if context:
        user_input += f" (Context: {', '.join(context)})"
    if re.search(r"\b(kill|suicide|die|hurt)\b", user_input, re.IGNORECASE):
        return {"response": "⚠️ **Safety Alert:** Please contact emergency services immediately."}

    try:
        response_data = get_rag_chain().invoke(
            {"input": user_input, "history": recent_chat_history(data.session_id)}
        )
        truncated = False
        if isinstance(response_data, AIMessage):
            bot_text = response_data.text
            truncated = response_data.response_metadata.get("finish_reason") == "length"
        elif isinstance(response_data, dict):
            bot_text = response_data.get(
                "answer", response_data.get("result", str(response_data))
            )
            if bot_text is None:
                bot_text = str(response_data)
        else:
            bot_text = response_data
        clean_response = bot_text.replace("*", "").strip()
        save_message(data.session_id, "User", data.symptoms)
        save_message(data.session_id, "Therapist", clean_response)
        result: dict[str, str | bool] = {"response": clean_response}
        if truncated:
            result["truncated"] = True
        return result
    except MissingGroqKeyError:
        return JSONResponse(
            status_code=503,
            content={"error": "Set GROQ_API_KEY in .env or the server environment to enable chat."},
        )
    except RateLimitError as exc:
        return groq_rate_limit_response(exc)
    except AuthenticationError:
        return JSONResponse(
            status_code=503,
            content={"error": "Groq rejected the API key. Check GROQ_API_KEY and restart the server."},
        )
    except PermissionDeniedError:
        return JSONResponse(
            status_code=403,
            content={"error": "Groq blocked this model for your organization or project. Enable it in Groq model permissions or set GROQ_MODEL to an allowed model."},
        )
    except APITimeoutError:
        logger.warning("Groq chat request timed out")
        return JSONResponse(
            status_code=504,
            content={"error": "Groq took too long to respond. Your message is ready to retry."},
        )
    except APIConnectionError:
        logger.warning("Could not connect to Groq")
        return JSONResponse(
            status_code=503,
            content={"error": "Could not connect to Groq. Please retry your message."},
        )
    except Exception as exc:
        logger.error("Chat request failed (%s)", type(exc).__name__)
        return JSONResponse(
            status_code=502,
            content={"error": "I am having trouble accessing Groq or the local knowledge index."},
        )
