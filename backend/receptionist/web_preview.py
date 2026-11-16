"""Local operator preview. Run separately from both Cloud Run services."""
import hashlib
import json
import logging
import os
import re
import secrets
import subprocess
import time
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from time import monotonic
from typing import Literal
from uuid import UUID

import httpx
import jwt
from fastapi import FastAPI, HTTPException, Request, Response
from google.cloud import firestore, secretmanager
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import PROJECT
from .market_client import search as search_market
from .web_market import reviewed_market_context

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
ASSISTANT_ID = "8a1073de-713e-425d-8674-22e285e26d2e"
ORG_ID = "49a210b5-a8cb-4d08-9309-756028a0d537"
DISCLOSURE = "web-voice-v1"
log = logging.getLogger(__name__)


@app.middleware("http")
async def local_bridge_only(request: Request, next_handler):
    if request.client.host != "127.0.0.1" or "origin" in request.headers:
        return Response(status_code=403)
    return await next_handler(request)


@lru_cache(maxsize=1)
def _clients(token_window):
    creds = None
    if token_window:
        from google.oauth2.credentials import Credentials
        token = subprocess.check_output(["gcloud", "auth", "print-access-token"], timeout=20)
        creds = Credentials(token.decode().strip())
    return (firestore.Client(project=PROJECT, database="receptionist-staging", credentials=creds),
            secretmanager.SecretManagerServiceClient(credentials=creds, transport="rest"))


def clients():
    return _clients(int(monotonic() // 240) + 1 if os.getenv("WEB_PREVIEW_GCLOUD_USER") == "true" else 0)


def provider(path, body=None, method="POST"):
    _, manager = clients()
    key = manager.access_secret_version(
        name=f"projects/{PROJECT}/secrets/vapi-api-key/versions/latest", timeout=8
    ).payload.data.decode().strip()
    if path == "call/web":
        key = jwt.encode({"orgId": ORG_ID, "exp": int(time.time()) + 60, "token": {
            "tag": "public", "restrictions": {"allowedAssistantIds": [ASSISTANT_ID]},
        }}, key, algorithm="HS256")
    request = httpx.get if method == "GET" else httpx.post
    response = request("https://api.vapi.ai/" + path, **({"json": body} if method != "GET" else {}),
                          headers={"Authorization": "Bearer " + key}, timeout=65)
    if not response.is_success:
        log.warning("Staging %s returned %d", path, response.status_code)
        raise HTTPException(503, "Website assistant unavailable")
    return response.json()


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=1200)


class Session(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session: UUID
    language: Literal["en", "es"]
    history: list[Turn] = Field(max_length=24)


class Chat(Session):
    question: str = Field(min_length=1, max_length=2000)
    previous: UUID | None = None
    # Accept older preview clients while routing every conversation automatically.
    topic: Literal["gizelle", "news"] | None = None


class Consent(Session):
    accepted: StrictBool
    version: Literal["web-voice-v1"]


class Join(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session: UUID
    ticket: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


def overrides(session):
    return {"variableValues": {
        "gz_language": session.language,
        "gz_session": str(session.session),
        "gz_market": "" if os.getenv("WEB_RETRIEVAL_TOOL") == "true" else reviewed_market_context(),
        "gz_handoff": json.dumps([turn.model_dump() for turn in session.history], ensure_ascii=False),
    }}


@app.post("/chat")
def chat(value: Chat):
    company_question = re.search(
        r"getzelling|services?|servicios?|fees?|comisi[oó]n|tarifas?|appointments?|citas?|"
        r"contact|listing presentation|plan de venta|selling my|sell my|vender mi|correo|email|^(hello|hi|hola|buenas)\b",
        value.question, re.IGNORECASE)
    market_question = re.search(
        r"\bmarket\b|\bmercado\b|condos?|condominios?|home prices|precios de|"
        r"Fisher Island|Palm Beach luxury|lujo en Palm Beach", value.question, re.IGNORECASE)
    action_request = re.search(
        r"schedule|book|agendar|programar|\b(send|request|quiero|solicitar|enviar)\b.*"
        r"(report|informe)|\b(like|want)\b.*\breport\b", value.question, re.IGNORECASE)
    if not action_request and (market_question or not company_question):
        result = search_market(value.question)
        if result.get("intent") in ("historical", "current"):
            return {"answer": result["answer"].replace("this archive", "Market insights").replace("este archivo", "Market insights"), "citations": result["citations"],
                    "previous": str(value.previous) if value.previous else None, "corpus_id": result.get("corpus_id")}
    payload = {"input": value.question, "assistantId": ASSISTANT_ID, "assistantOverrides": overrides(value)}
    db, _ = clients()
    if value.previous:
        prior = db.collection("web_preview_chats").document(str(value.previous)).get().to_dict() or {}
        if prior.get("session_id") != str(value.session):
            raise HTTPException(403, "Chat session mismatch")
        payload["previousChatId"] = str(value.previous)
    db.collection("web_text_sessions").document(str(value.session)).set({
        "expires_at": datetime.now(UTC) + timedelta(hours=2),
    })
    reply = provider("chat", payload)
    text = "\n".join(m.get("content") or m.get("message") or "" for m in reply.get("output", [])
                     if m.get("role") in ("assistant", "bot")).strip()
    captures = {tool["id"] for m in reply.get("output", []) for tool in m.get("tool_calls", [])
                if (tool.get("function") or {}).get("name") == "capture-lead"}
    saved = {m.get("tool_call_id") for m in reply.get("output", [])
             if m.get("role") == "tool" and "GZ_INQUIRY_SAVED" in str(m.get("content") or "")}
    if captures and not captures.issubset(saved):
        text = ("Todavía no he guardado su consulta. Confirme su correo exacto o un número de teléfono completo para volver a intentarlo. También puede escribirme a gizelle@getzelling.com."
                if value.language == "es" else
                "I haven't saved your inquiry yet. Please confirm your exact email or complete callback number so I can try again. You can also email me at gizelle@getzelling.com.")
    if not text:
        raise HTTPException(502, "No assistant reply")
    chat_id = str(UUID(reply["id"]))
    db.collection("web_preview_chats").document(chat_id).set({"session_id": str(value.session)})
    return {"answer": text, "previous": chat_id}


def grant_ref(db, ticket):
    return db.collection("web_voice_grants").document(hashlib.sha256(ticket.encode()).hexdigest())


@app.post("/consent")
def consent(value: Consent):
    if value.accepted is not True:
        raise HTTPException(422, "Affirmative consent required")
    db, _ = clients()
    ticket = secrets.token_urlsafe(32)
    grant_ref(db, ticket).create({
        "session_id": str(value.session), "accepted": True, "language": value.language,
        "version": value.version, "granted_at": firestore.SERVER_TIMESTAMP,
        "handoff": [turn.model_dump() for turn in value.history],
        "expires_at": datetime.now(UTC) + timedelta(minutes=3),
    })
    return {"ticket": ticket}


@app.post("/voice")
def voice(value: Join):
    db, _ = clients()
    grant = grant_ref(db, value.ticket)

    @firestore.transactional
    def consume(tx):
        audit = grant.get(transaction=tx).to_dict() or {}
        if (audit.get("session_id") != str(value.session) or audit.get("accepted") is not True
                or audit.get("version") != DISCLOSURE or audit.get("used_at")
                or audit["expires_at"] <= datetime.now(UTC)):
            raise HTTPException(403, "A new consent is required")
        tx.update(grant, {"used_at": firestore.SERVER_TIMESTAMP, "handoff": firestore.DELETE_FIELD})
        return audit

    audit = consume(db.transaction())
    session = Session(session=value.session, language=audit["language"], history=audit["handoff"])
    settings = overrides(session)
    if session.language == "es":
        settings["firstMessage"] = "Soy Gizelle, de GetZelling. ¿En qué puedo ayudarle?"
    call = provider("call/web", {"assistantId": ASSISTANT_ID, "assistantOverrides": settings,
                                 "roomDeleteOnUserLeaveEnabled": True})
    call_id = str(UUID(call["id"]))
    batch = db.batch()
    batch.create(db.collection("voice_consents").document(call_id), {
        **{k: audit[k] for k in ("session_id", "language", "version", "accepted", "granted_at")},
        "consent_basis": "agree-and-call", "channel": "web",
    })
    batch.update(grant, {"call_id": call_id})
    batch.commit()
    transport = call.get("transport") or {}
    return {"id": call_id, "webCallUrl": transport.get("callUrl") or call["webCallUrl"],
            "transport": {k: transport[k] for k in ("callToken",) if k in transport}}
