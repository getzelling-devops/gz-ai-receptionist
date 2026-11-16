"""Audit historical CRM leads by default. --apply imports eligible non-test leads."""
import argparse
from collections import Counter
import json
import re
from uuid import UUID

import httpx

from receptionist.brevo_contacts import e164, payload, provision_attributes, sync_lead, verify_lists
from receptionist.web_preview import clients


def skip_reason(lead):
    if lead.get("is_test") or lead.get("test_run"):
        return "test"
    identifier = str(lead.get("call_id") or "")
    text = " ".join(str(lead.get(k) or "") for k in ("name", "summary", "lead_type"))
    if identifier.startswith(("synthetic-", "test-")) or re.search(
            r"\b(synthetic|automated (?:qa|test)|internal (?:layout|connection|test)|staging test|test call|test lead|calendar test|quality test|testing the greeting)\b", text, re.I):
        return "test"
    contact = payload(lead)
    if not contact:
        return "no_verified_identifier"
    email = contact.get("email") or ""
    if email.rsplit("@", 1)[-1] in ("example.com", "example.org", "example.net") or email.endswith((".test", ".invalid")):
        return "test"
    phone = contact.get("phone") or ""
    if re.fullmatch(r"\+1\d{3}55501\d{2}", phone):
        return "test"
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    db, manager = clients()
    totals = Counter(); pending = []
    for item in db.collection("leads").stream():
        lead = item.to_dict()
        reason = skip_reason(lead)
        if reason:
            totals["skipped_" + reason] += 1
        else:
            pending.append(lead)
            for role in payload(lead)["roles"]:
                totals["eligible_" + role] += 1
    totals["eligible_leads"] = len(pending)
    print(json.dumps(dict(totals), sort_keys=True), flush=True)
    if not args.apply:
        print("Dry run only; Brevo unchanged.")
        return
    key = manager.access_secret_version(name="projects/gz-ai-receptionist/secrets/brevo-api-key/versions/latest").payload.data.decode().strip()
    with httpx.Client(base_url="https://api.brevo.com/v3", headers={"api-key": key}, timeout=15) as client:
        verify_lists(client)
        provision_attributes(client)
        vapi_key = manager.access_secret_version(name="projects/gz-ai-receptionist/secrets/vapi-api-key/versions/latest").payload.data.decode().strip()
        with httpx.Client(base_url="https://api.vapi.ai", headers={"Authorization": "Bearer " + vapi_key}, timeout=20) as calls:
            for lead in pending:
                if not lead.get("channel"):
                    try:
                        cid = str(UUID(lead["call_id"]))
                        response = calls.get("/call/" + cid); response.raise_for_status()
                        kind = response.json().get("type")
                        lead["channel"] = "web_voice" if kind == "webCall" else "phone" if kind in ("inboundPhoneCall", "outboundPhoneCall") else "unknown"
                    except (ValueError, httpx.HTTPError):
                        lead["channel"] = "unknown"
                ref = sync_lead(db, lead, client=client)
                result = ref.get().to_dict()
                totals["result_" + result["status"]] += 1
    print(json.dumps(dict(totals), sort_keys=True))

if __name__ == "__main__":
    main()
