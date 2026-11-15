"""Hosted private website pilot. Visitor sessions and signed Vapi tools."""
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from firebase_admin import firestore
from pydantic import BaseModel, ConfigDict, Field

from . import web_preview as service
from .market_client import search
from .security import signed_message

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
log = logging.getLogger(__name__)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def limit(key, maximum, window=3600):
    db, _ = service.clients()
    now = datetime.now(UTC)
    slot = int(now.timestamp()) // window
    ref = db.collection("web_usage").document(digest(f"{key}:{slot}"))

    @firestore.transactional
    def claim(tx):
        count = (ref.get(transaction=tx).to_dict() or {}).get("count", 0)
        if count >= maximum:
            raise HTTPException(429, "Please try again later")
        tx.set(ref, {"count": count + 1, "expires_at": now + timedelta(seconds=window * 2)})
    claim(db.transaction())


@app.middleware("http")
async def boundary(request, next_handler):
    # Cloud Run has no body-size option. Bound streamed input before JSON parsing.
    if request.method == "POST":
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 140000:
                from fastapi.responses import Response
                return Response(status_code=413)
        request._body = bytes(data)
    response = await next_handler(request)
    response.headers["Cache-Control"] = "no-store"
    return response


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=256)


@app.post("/session")
def login(value: Login, request: Request):
    # Only Cloud Run's appended client IP is used for login throttling.
    address = request.headers.get("x-forwarded-for", "").split(",")[-1].strip() or request.client.host
    limit("login:" + digest(address), 20)
    _, manager = service.clients()
    key = manager.access_secret_version(
        name=f"projects/{service.PROJECT}/secrets/gizelle-preview-access/versions/latest", timeout=8
    ).payload.data.decode().strip()
    if not hmac.compare_digest(value.code, key):
        raise HTTPException(401, "Check your preview code")
    token = secrets.token_urlsafe(32)
    sid = str(uuid4())
    db, _ = service.clients()
    db.collection("web_sessions").document(digest(token)).create({
        "session_id": sid, "expires_at": datetime.now(UTC) + timedelta(hours=2),
        "created_at": firestore.SERVER_TIMESTAMP,
    })
    return {"session_token": token, "session_id": sid}


def visitor(request: Request):
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer ") or len(authorization) > 100:
        raise HTTPException(401, "Preview access required")
    token = authorization[7:]
    db, _ = service.clients()
    ref = db.collection("web_sessions").document(digest(token))
    session = ref.get().to_dict() or {}
    if not session or session["expires_at"] <= datetime.now(UTC):
        raise HTTPException(401, "Preview access expired")
    limit("session:" + digest(token), 120)
    limit("preview-inference", 500, 86400)
    return ref, session


Visitor = Annotated[tuple, Depends(visitor)]


def owns(value, session):
    if str(value.session) != session["session_id"]:
        raise HTTPException(403, "Session mismatch")


@app.post("/chat")
def chat(value: service.Chat, member: Visitor):
    _, session = member
    owns(value, session)
    try:
        return service.chat(value)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("Web chat unavailable (%s)", type(exc).__name__)
        raise HTTPException(503, "Gizelle is temporarily unavailable") from None


@app.post("/consent")
def consent(value: service.Consent, member: Visitor):
    ref, session = member
    owns(value, session)
    ticket = service.consent(value)["ticket"]
    ref.update({"voice_ticket": ticket})
    return {"accepted": True}


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assistantId: str


@app.post("/voice")
def voice(value: Start, member: Visitor):
    ref, session = member
    if value.assistantId != session["session_id"] or not session.get("voice_ticket"):
        raise HTTPException(403, "Affirmative consent required")
    limit("voice:" + session["session_id"], 5)
    call = service.voice(service.Join(session=session["session_id"], ticket=session["voice_ticket"]))
    ref.update({"voice_ticket": firestore.DELETE_FIELD, "call_id": call["id"]})
    return call


class CallStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call_id: UUID


@app.post("/call-status")
def call_status(value: CallStatus, member: Visitor):
    ref, session = member
    if str(value.call_id) != session.get("call_id"):
        raise HTTPException(403, "Call session mismatch")
    try:
        call = service.provider("call/" + str(value.call_id), method="GET")
        reason = call.get("endedReason") or None
        ref.update({"last_end_reason": reason, "call_checked_at": firestore.SERVER_TIMESTAMP})
        return {"status": call.get("status"), "ended_reason": reason}
    except Exception as exc:
        log.warning("Call status unavailable (%s)", type(exc).__name__)
        raise HTTPException(503, "Call status unavailable") from None


@app.post("/tools/market-insights")
def market(message: Annotated[dict, Depends(signed_message)]):
    if message.get("type") != "tool-calls":
        raise HTTPException(422)
    conversation = message.get("call") or message.get("chat") or {}
    if conversation.get("assistantId") != service.ASSISTANT_ID:
        raise HTTPException(403, "Website assistant required")
    cid = conversation.get("id")
    if not isinstance(cid, str) or len(cid) > 256:
        raise HTTPException(422)
    # Voice is authorized by its durable consent audit before join is offered.
    if conversation.get("type") == "webCall":
        db, _ = service.clients()
        audit = db.collection("voice_consents").document(cid).get().to_dict() or {}
        if audit.get("accepted") is not True:
            raise HTTPException(403, "Voice consent required")
    limit("tool:" + cid, 20)
    limit("preview-inference", 500, 86400)
    calls = message.get("toolCallList")
    if not isinstance(calls, list) or not 1 <= len(calls) <= 3:
        raise HTTPException(422)
    results = []
    for call in calls:
        try:
            fn = call.get("function", {})
            args = fn.get("arguments")
            if isinstance(args, str):
                args = json.loads(args)
            question = args.get("question") if isinstance(args, dict) else None
            if fn.get("name") != "market-insights" or not isinstance(question, str) or not 0 < len(question) <= 2000:
                raise ValueError("Invalid query")
            result = search(question)
            results.append({"toolCallId": call["id"], "result": json.dumps(result, ensure_ascii=False)})
            db, _ = service.clients()
            db.collection("web_market_results").document(digest(cid)).set({
                "conversation_id": cid, "citations": result["citations"],
                "corpus_id": result["corpus_id"], "updated_at": firestore.SERVER_TIMESTAMP,
            })
        except Exception as exc:
            log.warning("Market tool unavailable (%s)", type(exc).__name__)
            results.append({"toolCallId": call.get("id"), "error":
                            "Market insights is temporarily unavailable. Offer a team callback."})
    return {"results": results}


@app.get("/health")
def health():
    return {"service": "gizelle-web"}
