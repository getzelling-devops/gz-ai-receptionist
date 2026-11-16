"""Capture confirmed inquiries from Vapi chat or voice before CRM synchronization."""
import logging
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from . import brevo_contacts, records
from .contacts import confirmed_email, us_phone

PHONE_ASSISTANT = "83dbb599-ccda-4da2-a6ff-d17e9ce0cfd0"
WEB_ASSISTANT = "8a1073de-713e-425d-8674-22e285e26d2e"
log = logging.getLogger(__name__)


class LeadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=254)
    email_confirmed: StrictBool = False
    phone: str = Field(default="", max_length=50)
    phone_confirmed: StrictBool = False
    lead_types: list[Literal["buyer", "seller", "investor", "other"]] = Field(min_length=1, max_length=4)
    summary: str = Field(min_length=1, max_length=3000)


def capture(db, args, message):
    value = LeadInput.model_validate(args)
    chat = message.get("chat") or {}
    call = (message.get("call") or {}) if not chat else {}
    conversation = chat or call
    aid = conversation.get("assistantId") or (message.get("assistant") or {}).get("id")
    if aid not in (PHONE_ASSISTANT, WEB_ASSISTANT):
        raise ValueError("Unknown assistant")
    cid = str(UUID(conversation["id"]))
    if call:
        channel = "web_voice" if call.get("type") == "webCall" else "phone"
        if channel == "web_voice":
            audit = db.collection("voice_consents").document(cid).get().to_dict() or {}
            if aid != WEB_ASSISTANT or audit.get("accepted") is not True:
                raise ValueError("Voice consent required")
    else:
        if aid != WEB_ASSISTANT:
            raise ValueError("Website assistant required")
        settings = {**((chat.get("metadata") or {}).get("variableValues") or {}),
                    **((chat.get("assistantOverrides") or {}).get("variableValues") or {})}
        sid = str(UUID(settings["gz_session"]))
        session = db.collection("web_text_sessions").document(sid).get().to_dict() or {}
        if not session or session["expires_at"] <= datetime.now(UTC):
            raise ValueError("Website text session required")
        cid = "webtext:" + sid
        channel = "web_text"
    email = confirmed_email(value.email, value.email_confirmed)
    phone = us_phone(value.phone) if value.phone_confirmed else None
    if not email and not brevo_contacts.e164(phone):
        raise ValueError("Ask for an exact confirmed email or a complete confirmed callback number")
    prior_ref = (db.collection("leads").document(records.key_for("lead", cid)) if channel == "web_text"
                 else db.collection("lead_captures").document(records.key_for("capture", cid)))
    prior = prior_ref.get().to_dict() or {}
    roles = brevo_contacts.categories({"lead_types": [*value.lead_types, *prior.get("lead_types", [])]})
    email = email or confirmed_email(prior.get("email"), prior.get("email_confirmed"))
    phone = phone or prior.get("phone")
    lead = {"call_id": cid, "name": value.name or prior.get("name") or None, "email": email,
            "email_confirmed": bool(email), "phone": phone, "lead_types": roles,
            "lead_type": ",".join(roles), "summary": value.summary, "channel": channel,
            "timestamp": datetime.now(UTC).isoformat()}
    if channel == "web_text":
        messages = chat.get("messages") or []
        lead["transcript"] = "\n".join(
            f"{m['role']}: {m.get('content') or m.get('message') or ''}"
            for m in messages if m.get("role") in ("user", "assistant", "bot"))[:100000]
        delivery = records.save_lead(db, lead)
        # A later explicit correction replaces the earlier confirmed capture.
        db.collection("leads").document(records.key_for("lead", cid)).update(lead)
        try:
            records.deliver(db, delivery)
        except Exception as exc:
            log.warning("Text lead notification pending (%s)", type(exc).__name__)
    else:
        # The call-ended report still owns the full transcript/recording and email.
        db.collection("lead_captures").document(records.key_for("capture", cid)).set(lead)
    job = brevo_contacts.enqueue(db, lead)
    try:
        brevo_contacts.sync_job(db, job)
    except Exception as exc:
        log.warning("Brevo synchronization pending (%s)", type(exc).__name__)
    return {"result": "GZ_INQUIRY_SAVED. Confirmed inquiry saved for the GetZelling team. Do not claim a report or customer email was sent."}


def enrich_report(db, lead):
    capture = db.collection("lead_captures").document(records.key_for("capture", lead["call_id"])).get().to_dict() or {}
    for key in ("name", "email", "email_confirmed", "phone", "lead_types", "lead_type"):
        if capture.get(key):
            lead[key] = capture[key]
    return lead
