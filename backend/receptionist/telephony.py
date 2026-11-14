"""Twilio plays the notice before Vapi receives any caller audio."""
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
import re
import secrets
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from firebase_admin import firestore
from starlette.concurrency import run_in_threadpool
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import VoiceResponse

from .config import database, secret
from .security import signed_message

router = APIRouter(prefix="/telephony")
log = logging.getLogger(__name__)
DISCLOSURE_VERSION = "phone-en-es-2026-11-13-v2"
DISCLOSURES = (
    ("en-US", "This call will be recorded and transcribed for service and training. "
     "By continuing, you consent."),
    ("es-MX", "Esta llamada será grabada y transcrita para atención y capacitación. "
     "Al continuar, da su consentimiento."),
)
GATE_PATTERN = re.compile(r"gzgate_[0-9a-f]{48}")


def public_url(path):
    return os.environ["PUBLIC_BASE_URL"].rstrip("/") + path


def xml(response):
    return Response(str(response), media_type="application/xml")


def unavailable():
    response = VoiceResponse()
    response.say("We are unable to connect your call. Please email support at getzelling dot com.")
    response.hangup()
    return xml(response)


async def twilio_form(request: Request):
    signature = request.headers.get("x-twilio-signature", "")
    if not signature:
        raise HTTPException(401, "Missing Twilio signature")
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Expected a Twilio form")
    form = await request.form(max_fields=100, max_files=0, max_part_size=4096)
    token = await run_in_threadpool(secret, "TWILIO_AUTH_SECRET", "twilio-auth-token")
    url = public_url(request.url.path)
    if request.url.query:
        url += "?" + request.url.query
    if not RequestValidator(token.decode().strip()).validate(
        url, form, signature
    ):
        raise HTTPException(401, "Invalid Twilio signature")
    if form.get("AccountSid") != os.environ["TWILIO_ACCOUNT_SID"]:
        raise HTTPException(403, "Unexpected Twilio account")
    if not re.fullmatch(r"CA[0-9a-f]{32}", str(form.get("CallSid", ""))):
        raise HTTPException(422, "Missing call SID")
    return form


TwilioForm = Annotated[dict, Depends(twilio_form)]


@router.post("/twilio/inbound")
def inbound(form: TwilioForm):
    if form.get("To") != os.environ["TWILIO_PHONE_NUMBER"]:
        raise HTTPException(403, "Unexpected destination")
    try:
        db = database()
        ref = db.collection("phone_sessions").document(form["CallSid"])

        @firestore.transactional
        def begin(tx):
            if not ref.get(transaction=tx).exists:
                tx.create(ref, {
                    "twilio_call_id": form["CallSid"],
                    "disclosure_version": DISCLOSURE_VERSION,
                    "notice_started_at": datetime.now(UTC),
                    "caller": form.get("From"),
                    "status": "notice",
                })

        begin(db.transaction())
        response = VoiceResponse()
        for language, text in DISCLOSURES:
            response.say(text, language=language)
        response.pause(length=3)
        response.redirect(public_url("/telephony/twilio/connect"), method="POST")
        return xml(response)
    except Exception as exc:
        log.error("Phone notice unavailable (%s)", type(exc).__name__)
        return unavailable()


@router.post("/twilio/connect")
def connect(form: TwilioForm):
    try:
        db = database()
        ref = db.collection("phone_sessions").document(form["CallSid"])
        now = datetime.now(UTC)

        @firestore.transactional
        def continued(tx):
            session = ref.get(transaction=tx).to_dict()
            if (not session or now - session["notice_started_at"] < timedelta(seconds=3)
                    or now - session["notice_started_at"] > timedelta(minutes=10)):
                raise ValueError("Notice session missing or expired")
            if session.get("gate"):
                if session["gate_expires_at"] <= now:
                    raise ValueError("Gate expired")
                return session["gate"]
            gate = "gzgate_" + secrets.token_hex(24)
            expires = now + timedelta(minutes=2)
            tx.create(db.collection("phone_gates").document(gate), {
                "twilio_call_id": form["CallSid"], "expires_at": expires,
                "continued_at": now, "disclosure_version": session["disclosure_version"],
            })
            tx.update(ref, {"gate": gate, "gate_expires_at": expires,
                            "continued_at": now, "consent_basis": "stay-on-line",
                            "status": "connecting"})
            return gate

        gate = continued(db.transaction())
        response = VoiceResponse()
        dial = response.dial(record="do-not-record", timeout=25,
                             action=public_url("/telephony/twilio/finished"), method="POST")
        dial.sip(os.environ["VAPI_SIP_URI"] + "?" + urlencode({"X-gzgate": gate}))
        return xml(response)
    except Exception as exc:
        log.error("Phone connection unavailable (%s)", type(exc).__name__)
        return unavailable()


@router.post("/twilio/finished")
def finished(form: TwilioForm):
    try:
        database().collection("phone_sessions").document(form["CallSid"]).set(
            {"dial_status": form.get("DialCallStatus", "unknown"), "finished_at": datetime.now(UTC)},
            merge=True,
        )
    except Exception as exc:
        log.error("Phone completion audit failed (%s)", type(exc).__name__)
    if form.get("DialCallStatus") not in ("completed", "answered"):
        return unavailable()
    response = VoiceResponse()
    response.hangup()
    return xml(response)


def gate_values(value):
    # Vapi surfaces SIP template variables in different metadata containers.
    # A single-use random token must still match a persisted, unexpired session.
    if isinstance(value, dict):
        return set().union(*(gate_values(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(gate_values(v) for v in value)) if value else set()
    if isinstance(value, str):
        return set(GATE_PATTERN.findall(value))
    return set()


@router.post("/vapi/resolve")
def resolve(message: Annotated[dict, Depends(signed_message)]):
    if message.get("type") != "assistant-request":
        return {}
    try:
        call = message["call"]
        call_id = call["id"]
        tokens = gate_values(message)
        if len(tokens) != 1:
            raise ValueError("Missing unique gate token")
        gate = tokens.pop()
        db = database()
        ref = db.collection("phone_gates").document(gate)

        @firestore.transactional
        def claim(tx):
            record = ref.get(transaction=tx).to_dict()
            if not record or record["expires_at"] <= datetime.now(UTC):
                raise ValueError("Gate expired")
            if record.get("vapi_call_id") not in (None, call_id):
                raise ValueError("Gate already used")
            session = db.collection("phone_sessions").document(record["twilio_call_id"])
            tx.update(ref, {"vapi_call_id": call_id})
            tx.update(session, {"vapi_call_id": call_id, "status": "connected"})
            tx.set(db.collection("voice_consents").document(call_id), {
                "type": "stay-on-line", "grantedAt": record["continued_at"].isoformat(),
                "disclosure_version": record["disclosure_version"],
                "twilio_call_id": record["twilio_call_id"],
            })
            return record

        record = claim(db.transaction())
        overrides = json.loads(Path(__file__).with_name("phone_assistant.json").read_text())
        overrides["metadata"] = {"twilio_call_id": record["twilio_call_id"],
                                 "disclosure_version": record["disclosure_version"]}
        return {"assistantId": os.environ["VAPI_ASSISTANT_ID"], "assistantOverrides": overrides}
    except Exception as exc:
        log.error("Phone assistant rejected (%s)", type(exc).__name__)
        # Preserve only structural diagnostics, not raw headers or token values.
        log.info("SIP request fields: %s", sorted(message.get("call", {}).keys()))
        return {"error": "We are unable to connect your call. Please contact GetZelling by email."}
