"""Durable, additive Brevo list sync. Never subscribe, force-merge, or send campaigns."""
import hashlib
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx
from firebase_admin import firestore

from .config import secret
from .contacts import confirmed_email, us_phone

LISTS = {"buyer": (30, "gz-gizelle-buyers"), "seller": (31, "gz-gizelle-sellers"),
         "investor": (32, "gz-gizelle-investors"), "other": (33, "gz-gizelle-other")}
ATTRIBUTES = ("GIZELLE_FULL_NAME", "GIZELLE_SOURCE", "GIZELLE_LEAD_TYPES")
ALIASES = {"buying": "buyer", "buyers": "buyer", "comprador": "buyer", "compradores": "buyer",
           "selling": "seller", "sellers": "seller", "vendedor": "seller", "vendedores": "seller",
           "investors": "investor", "inversionista": "investor", "inversor": "investor",
           "listing presentation": "seller", "listing_presentation": "seller", "plan de venta": "seller",
           "sell": "seller", "vender": "seller", "buy": "buyer", "comprar": "buyer",
           "home buyer": "buyer", "buyer lead": "buyer", "seller lead": "seller",
           "selling a house": "seller", "selling a home": "seller", "selling property": "seller",
           "listing property": "seller", "listing inquiry": "seller"}
log = logging.getLogger(__name__)


class IdentityConflict(Exception):
    pass


def categories(lead):
    values = lead.get("lead_types") or [lead.get("lead_type") or "other"]
    if not isinstance(values, list):
        values = [values]
    roles = set()
    for value in values:
        for token in re.split(r"[,;/+&|]", str(value).lower()):
            token = token.strip()
            role = ALIASES.get(token, token)
            if role in LISTS:
                roles.add(role)
    specific = roles - {"other"}
    return sorted(specific or {"other"})


def e164(value):
    value = us_phone(value)
    if not isinstance(value, str):
        return None
    if re.fullmatch(r"[2-9]\d{2}-[2-9]\d{2}-\d{4}", value):
        return "+1" + value.replace("-", "")
    if value.startswith("+") and re.fullmatch(r"\+[0-9 ()-]+", value):
        digits = re.sub(r"\D", "", value)
        if not digits.startswith("1") and re.fullmatch(r"[1-9]\d{7,14}", digits):
            return "+" + digits
    return None


def payload(lead):
    email = confirmed_email(lead.get("email"), lead.get("email_confirmed"))
    phone = e164(lead.get("phone"))
    if not email and not phone:
        return None
    channel = {"web": "web_voice", "webCall": "web_voice"}.get(lead.get("channel"), lead.get("channel"))
    return {"email": email, "phone": phone, "name": (lead.get("name") or "")[:200],
            "roles": categories(lead), "channel": channel if channel in ("phone", "web_voice", "web_text") else "unknown"}


def enqueue(db, lead):
    value = payload(lead)
    if value is None:
        return None
    fingerprint = hashlib.sha256(json.dumps([lead["call_id"], value], sort_keys=True).encode()).hexdigest()
    ref = db.collection("brevo_contact_jobs").document(fingerprint)
    source = db.collection("brevo_contact_sources").document(hashlib.sha256(lead["call_id"].encode()).hexdigest())
    @firestore.transactional
    def persist(tx):
        old = source.get(transaction=tx).to_dict() or {}
        saved = ref.get(transaction=tx)
        if not saved.exists:
            tx.create(ref, {"payload": value, "conversation_id": lead["call_id"], "source_id": source.id,
                            "status": "pending", "created_at": firestore.SERVER_TIMESTAMP, "attempts": 0})
        elif saved.to_dict().get("status") == "superseded":
            tx.update(ref, {"status": "pending"})
        if old.get("job_id") != ref.id:
            tx.set(source, {"job_id": ref.id, "updated_at": firestore.SERVER_TIMESTAMP})
    persist(db.transaction())
    return ref


def verify_lists(client):
    for lid, name in LISTS.values():
        response = client.get(f"/contacts/lists/{lid}")
        response.raise_for_status()
        if response.json().get("name") != name:
            raise ValueError(f"Brevo list {lid} name does not match configuration")


def provision_attributes(client):
    response = client.get("/contacts/attributes"); response.raise_for_status()
    known = {a["name"]: a for a in response.json()["attributes"]}
    for name in ATTRIBUTES:
        if name in known:
            if known[name].get("type") != "text":
                raise ValueError("Unexpected Brevo attribute type: " + name)
        else:
            response = client.post("/contacts/attributes/normal/" + name, json={"type": "text"})
            response.raise_for_status()


def lookup(client, identifier, kind):
    response = client.get("/contacts/" + quote(identifier, safe=""), params={"identifierType": kind})
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def upsert(client, value, retry=True):
    email, phone = value["email"], value["phone"]
    by_email = lookup(client, email, "email_id") if email else None
    by_phone = lookup(client, phone, "phone_id") if phone else None
    if by_email and by_phone and by_email["id"] != by_phone["id"]:
        raise IdentityConflict("Email and phone identify different contacts")
    existing = by_email or by_phone
    if existing and email and existing.get("email") and existing["email"].lower() != email.lower():
        raise IdentityConflict("Phone belongs to a different email contact")
    attrs = (existing or {}).get("attributes") or {}
    roles = set(value["roles"]) | set(str(attrs.get("GIZELLE_LEAD_TYPES") or "").split(","))
    sources = {value["channel"]} | set(str(attrs.get("GIZELLE_SOURCE") or "").split(","))
    update = {"GIZELLE_SOURCE": ",".join(sorted(sources - {""})),
              "GIZELLE_LEAD_TYPES": ",".join(sorted(roles - {""}))}
    if value["name"] and not attrs.get("GIZELLE_FULL_NAME"):
        update["GIZELLE_FULL_NAME"] = value["name"]
    if phone and not attrs.get("SMS"):
        update["SMS"] = phone
    lists = [LISTS[r][0] for r in value["roles"]]
    # List-level opt-outs are as binding as the global preference.
    opted_out = set((existing or {}).get("listUnsubscribed") or [])
    lists = [lid for lid in lists if lid not in opted_out]
    if existing:
        body = {"attributes": update, "listIds": lists}
        if email and not existing.get("email"):
            # Brevo can clear blocking when EMAIL changes. Do not enrich a blocked
            # phone-only contact automatically; keep it for a person's review.
            if existing.get("emailBlacklisted"):
                raise IdentityConflict("Blocked phone-only contact needs email review")
            update["EMAIL"] = email
        response = client.put("/contacts/" + str(existing["id"]), json=body)
        response.raise_for_status()
        return existing["id"]
    body = {"attributes": update, "listIds": lists, "updateEnabled": False, "forceMerge": False}
    if email:
        body["email"] = email
    response = client.post("/contacts", json=body)
    if retry and response.status_code == 400 and response.json().get("code") == "duplicate_parameter":
        # A concurrent request or a lost 201 may have created this identity.
        found = lookup(client, email or phone, "email_id" if email else "phone_id")
        if found:
            return upsert(client, value, retry=False)
    response.raise_for_status()
    return response.json()["id"]


def sync_job(db, ref, client=None):
    now = datetime.now(UTC)
    @firestore.transactional
    def claim(tx):
        job = ref.get(transaction=tx).to_dict()
        if job["status"] in ("synced", "review", "superseded") or job.get("lease_until", now) > now:
            return None
        if job.get("source_id"):
            source = db.collection("brevo_contact_sources").document(job["source_id"]).get(transaction=tx).to_dict() or {}
            if source.get("job_id") != ref.id:
                tx.update(ref, {"status": "superseded", "lease_until": firestore.DELETE_FIELD})
                return None
        tx.update(ref, {"lease_until": now + timedelta(seconds=90), "attempts": job.get("attempts", 0) + 1})
        return job
    job = claim(db.transaction())
    if not job:
        return
    try:
        if client is None:
            key = secret("BREVO_API_SECRET", "brevo-api-key").decode()
            with httpx.Client(base_url="https://api.brevo.com/v3", headers={"api-key": key}, timeout=10) as connection:
                cid = upsert(connection, job["payload"])
        else:
            cid = upsert(client, job["payload"])
        ref.update({"status": "synced", "contact_id": cid, "synced_at": firestore.SERVER_TIMESTAMP,
                    "lease_until": firestore.DELETE_FIELD, "last_error": firestore.DELETE_FIELD})
    except IdentityConflict:
        ref.update({"status": "review", "last_error": "identity_conflict", "lease_until": firestore.DELETE_FIELD})
        log.warning("Brevo contact needs identity review")
    except Exception as exc:
        ref.update({"status": "pending", "last_error": type(exc).__name__, "lease_until": firestore.DELETE_FIELD})
        raise


def sync_lead(db, lead, client=None):
    ref = enqueue(db, lead)
    if ref:
        sync_job(db, ref, client=client)
    return ref
