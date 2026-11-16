import json
import logging
import os
import time
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from google.api_core.exceptions import AlreadyExists

from .booking import Calendar, ToolError, availability, book
from . import brevo_contacts, lead_capture
from .config import database
from .records import deliver, extract_lead, key_for, notification, obj, save_lead
from .security import signed_message
from .rescheduling import reschedule
from .telephony import router as telephony_router

app = FastAPI(title="GetZelling receptionist", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(telephony_router)
Message = Annotated[dict, Depends(signed_message)]
log = logging.getLogger(__name__)


def conversation_id(message):
    for field in ("call", "chat"):
        value = obj(message.get(field)).get("id")
        if isinstance(value, str) and 0 < len(value) <= 256:
            return value
    raise HTTPException(422, "Missing conversation ID")


@app.post("/webhooks/call-ended")
def call_ended(message: Message):
    if message.get("type") != "end-of-call-report" or not obj(message.get("call")).get("id"):
        raise HTTPException(422, "Expected an end-of-call report")
    conversation_id(message)
    try:
        db = database()
        lead = lead_capture.enrich_report(db, extract_lead(message))
        consent = db.collection("voice_consents").document(lead["call_id"]).get()
        if consent.exists:
            lead["recording_consent"] = consent.to_dict()
        delivery = save_lead(db, lead)
        failures = []
        for action in (lambda: deliver(db, delivery), lambda: brevo_contacts.sync_lead(db, lead)):
            try:
                action()
            except Exception as exc:
                failures.append(type(exc).__name__)
        if failures:
            raise RuntimeError("Lead delivery pending")
    except Exception as exc:
        # Provider exception bodies may contain personal data or credentials.
        log.error("Call report processing failed (%s)", type(exc).__name__)
        raise HTTPException(503, "Call report delivery pending. Retry this report.") from None
    return {"received": True}


def escalate(db, operation, args):
    reason = args.get("message")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 3000:
        raise ToolError("Supply a short urgent message for the GetZelling team.")
    callback = args.get("phone") or "Not provided"
    body = f"{reason}\nCallback: {callback}"
    # One incident per tool invocation. One independent delivery record per destination.
    refs = []
    batch = db.batch()
    for channel, address in (("support", "support@getzelling.com"), ("on_call", os.getenv("ON_CALL_EMAIL"))):
        ref = db.collection("deliveries").document(key_for("urgent", operation, channel))
        refs.append(ref)
        batch.create(ref, notification(address, "Urgent GetZelling handoff", body))
    try:
        batch.commit()
    except AlreadyExists:
        pass
    pending = False
    for ref in refs:
        try:
            deliver(db, ref)
        except Exception as exc:
            log.error("Urgent notification pending (%s)", type(exc).__name__)
            pending = True
    if pending:
        raise ToolError("Urgent message saved. Notification delivery is pending. Attempt the live transfer now.")
    return {"result": "Support and on-call notifications accepted. Attempt the live transfer now."}


@app.post("/tools/{tool_name}")
def tools(tool_name: str, message: Message):
    if tool_name not in {"check-availability", "book-appointment", "reschedule-appointment",
                         "escalate-urgent", "finish-call", "capture-lead"}:
        raise HTTPException(404)
    calls = message.get("toolCallList")
    if message.get("type") != "tool-calls" or not isinstance(calls, list) or not calls:
        raise HTTPException(422, "Expected a nonempty toolCallList")
    conversation = conversation_id(message)
    if any(not isinstance(obj(c).get("id"), str) or not c["id"] for c in calls):
        raise HTTPException(422, "Missing tool call ID")
    results = []
    for call in calls:
        try:
            function = obj(call.get("function"))
            if function.get("name") != tool_name:
                raise ToolError("Tool name does not match its configured endpoint.")
            args = function.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    raise ToolError("Invalid tool arguments.") from None
            if not isinstance(args, dict):
                raise ToolError("Expected an object of tool arguments.")
            if tool_name == "finish-call":
                # Vapi finishes the reserved bot_say playback before invoking us.
                # Closing must not depend on Calendar, Firestore or email delivery.
                # Let the completed farewell's final audio packets reach the caller
                # before the model receives permission to hang up the phone leg.
                time.sleep(1.0)
                results.append({"toolCallId": call["id"], "result":
                                "GZ_FAREWELL_COMPLETE. Now invoke end_getzelling_call without additional speech."})
                continue
            db = database()
            if tool_name == "capture-lead":
                try:
                    reply = lead_capture.capture(db, args, message)
                except (ValueError, KeyError):
                    raise ToolError("Confirm an exact email or complete callback number and the visitor's stated interest before saving the inquiry.") from None
            elif tool_name == "escalate-urgent":
                reply = escalate(db, key_for(conversation, call["id"]), args)
            else:
                cal = Calendar()
                try:
                    if tool_name == "book-appointment":
                        reply = book(db, cal, key_for("booking", conversation, call["id"]), args, conversation)
                    elif tool_name == "reschedule-appointment":
                        reply = reschedule(db, cal, key_for("reschedule", conversation, call["id"]), args, conversation)
                    else:
                        reply = availability(db, cal, args, conversation)
                finally:
                    cal.http.close()
        except ToolError as exc:
            reply = {"error": str(exc)}
        except Exception as exc:
            log.error("Tool %s unavailable (%s)", tool_name, type(exc).__name__)
            reply = {"error": "Service unavailable. Offer a team callback. Do not promise completion."}
        results.append({"toolCallId": call["id"], **reply})
    return {"results": results}
