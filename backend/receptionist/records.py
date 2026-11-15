import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

import httpx
from firebase_admin import firestore

from .config import secret
from .contacts import confirmed_email, us_phone
from .mail import render


def key_for(*parts):
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


def obj(value):
    return value if isinstance(value, dict) else {}


def string(*values):
    return next((value for value in values if isinstance(value, str) and value.strip()), None)


def extract_lead(message):
    call = obj(message.get("call"))
    artifact = {**obj(call.get("artifact")), **obj(message.get("artifact"))}
    analysis = obj(message.get("analysis") or call.get("analysis"))
    fields = obj(analysis.get("structuredData")).copy()
    for output in obj(artifact.get("structuredOutputs")).values():
        if obj(output).get("name") == "getzelling_lead":
            fields.update(obj(output.get("result")))
    recording = obj(artifact.get("recording"))
    customer = obj(message.get("customer") or call.get("customer"))
    consent = obj(obj(message.get("compliance") or call.get("compliance")).get("recordingConsent"))
    consent_missing = bool(consent) and not consent.get("grantedAt")
    return {
        "call_id": call["id"],
        "name": string(fields.get("name"), customer.get("name")),
        "phone": us_phone(string(fields.get("phone"), customer.get("number"))),
        "email": confirmed_email(fields.get("email"), fields.get("email_confirmed")),
        "email_confirmed": fields.get("email_confirmed") is True,
        "channel": "web" if call.get("type") == "webCall" else "phone",
        "lead_type": string(fields.get("lead_type")),
        "summary": string(fields.get("summary"), analysis.get("summary"), message.get("summary")),
        "transcript": None if consent_missing else string(artifact.get("transcript"), message.get("transcript")),
        "recording_url": None if consent_missing else string(obj(recording.get("mono")).get("combinedUrl"), recording.get("stereoUrl"),
                                artifact.get("recordingUrl"), artifact.get("stereoRecordingUrl"),
                                message.get("recordingUrl"), message.get("stereoRecordingUrl")),
        "timestamp": string(message.get("endedAt"), call.get("endedAt")) or firestore.SERVER_TIMESTAMP,
        "recording_consent": consent,
    }


def notification(to, subject, body, lead=None):
    return {"to": to, "subject": subject, "body": body, "html": render(subject, body, lead),
            "reply_to": confirmed_email((lead or {}).get("email"), (lead or {}).get("email_confirmed")), "status": "pending"}


def save_lead(db, lead):
    doc_id = key_for("lead", lead["call_id"])
    ref = db.collection("leads").document(doc_id)
    delivery = db.collection("deliveries").document(doc_id)
    data = lead.copy()
    transcript = data.get("transcript") or ""
    chunks = []
    if len(transcript.encode()) > 512_000:
        chunks = [transcript[i:i + 100_000] for i in range(0, len(transcript), 100_000)]
        data.update(transcript=None, transcript_chunks=len(chunks))
    body = "\n".join(f"{key}: {lead.get(key) or 'Unknown'}" for key in ("name", "email", "phone", "lead_type", "summary"))
    mail = notification(os.getenv("LEAD_EMAIL", "activate@getzelling.com"), "GetZelling · New Gizelle inquiry", body, lead)

    @firestore.transactional
    def persist(tx):
        prior = ref.get(transaction=tx)
        if prior.exists:
            # A later report may supply analysis or recording after the first delivery.
            old = prior.to_dict()
            updates = {
                k: v for k, v in data.items() if v and not old.get(k)
            }
            if old.get("transcript_chunks") or old.get("transcript"):
                updates.pop("transcript_chunks", None)
                updates.pop("transcript", None)
            if updates:
                tx.update(ref, updates)
            if "transcript_chunks" not in updates:
                return
        else:
            tx.create(ref, data)
            tx.create(delivery, mail)
        for index, chunk in enumerate(chunks):
            tx.set(ref.collection("transcript_parts").document(f"{index:05}"), {"text": chunk})

    persist(db.transaction())
    return delivery


class DeliveryReview(Exception):
    pass


def deliver(db, ref):
    """A retry within the provider window uses the same persisted body and UUID."""
    now = datetime.now(UTC)

    @firestore.transactional
    def begin(tx):
        job = ref.get(transaction=tx).to_dict()
        if job["status"] == "sent":
            return None
        if job.get("first_attempt") and now - job["first_attempt"] >= timedelta(minutes=25):
            tx.update(ref, {"status": "review"})
            return "review"
        if not job.get("first_attempt"):
            tx.update(ref, {"first_attempt": now})
        return job

    # Configuration failures before first_attempt should remain safely replayable.
    saved = ref.get().to_dict()
    if saved["status"] == "sent":
        return
    address = saved["to"] or os.environ["ON_CALL_EMAIL"]
    sender = os.environ["BREVO_SENDER"]
    api_key = secret("BREVO_API_SECRET", "brevo-api-key").decode()
    job = begin(db.transaction())
    if job is None:
        return
    if job == "review":
        raise DeliveryReview("Check Brevo delivery history before resending")
    delivery_key = str(uuid5(NAMESPACE_URL, ref.path))
    response = httpx.post("https://api.brevo.com/v3/smtp/email", timeout=5,
                          headers={"api-key": api_key}, json={
                              "sender": {"email": sender, "name": "GetZelling"},
                              "to": [{"email": address}], "subject": job["subject"],
                              "htmlContent": job.get("html") or render(job["subject"], job["body"]),
                              **({"replyTo": {"email": job["reply_to"]}} if job.get("reply_to") else {}),
                              "textContent": job["body"], "headers": {"idempotencyKey": delivery_key},
                          })
    if response.status_code != 201:
        duplicate = (response.status_code == 400 and
                     response.json().get("code") == "duplicate_parameter" and
                     "idempot" in str(response.json().get("message", "")).lower())
        if not duplicate:
            response.raise_for_status()
            raise RuntimeError("Unexpected Brevo response")
    ref.update({"status": "sent", "accepted_at": firestore.SERVER_TIMESTAMP})
