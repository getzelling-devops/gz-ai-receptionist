import copy
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from receptionist import brevo_contacts as b, lead_capture as capture

LEAD = {"call_id": "example-call", "name": "Alex Example", "email": "a.b@example.com",
        "email_confirmed": True, "phone": "954 77. 0. 8. 428", "lead_types": ["buyer", "seller"], "channel": "web_voice"}

class BrevoContacts(unittest.TestCase):
    def test_classification_is_explicit_and_multiple_interests_are_supported(self):
        self.assertEqual(b.categories(LEAD), ["buyer", "seller"])
        self.assertEqual(b.categories({"lead_type": "Inversionista"}), ["investor"])
        self.assertEqual(b.categories({"lead_type": "Listing Presentation"}), ["seller"])
        self.assertEqual(b.categories({"lead_types": ["other", "buyer"]}), ["buyer"])
        self.assertEqual(b.categories({"lead_type": "not a buyer"}), ["other"])

    def test_only_confirmed_email_and_complete_phone_identify_a_contact(self):
        self.assertEqual(b.payload(LEAD)["email"], "a.b@example.com")
        self.assertEqual(b.payload(LEAD)["phone"], "+19547708428")
        self.assertIsNone(b.payload({"email": "a.b@example.com", "email_confirmed": False}))
        self.assertIsNone(b.e164("+15550100"))
        self.assertIsNone(b.e164("954-770"))
        self.assertEqual(b.e164("+34 600 123 456"), "+34600123456")

    def client(self, handler):
        return httpx.Client(base_url="https://api.brevo.com/v3", transport=httpx.MockTransport(handler))

    def test_existing_contact_keeps_preferences_and_other_lists(self):
        changes = []
        existing = {"id": 7, "email": "a.b@example.com", "emailBlacklisted": True, "smsBlacklisted": True,
                    "listIds": [9, 30], "listUnsubscribed": [31], "attributes": {"SMS": "+19547708428", "FIRSTNAME": "Existing", "GIZELLE_SOURCE": "phone"}}
        def respond(request):
            if request.method == "GET": return httpx.Response(200, json=existing)
            changes.append(__import__('json').loads(request.content))
            return httpx.Response(204)
        with self.client(respond) as client:
            self.assertEqual(b.upsert(client, b.payload(LEAD)), 7)
        self.assertEqual(changes[0]["listIds"], [30])
        self.assertNotIn("emailBlacklisted", changes[0]); self.assertNotIn("smsBlacklisted", changes[0])
        self.assertNotIn("unlinkListIds", changes[0]); self.assertNotIn("EMAIL", changes[0]["attributes"])
        self.assertNotIn("FIRSTNAME", changes[0]["attributes"])
        self.assertEqual(changes[0]["attributes"]["GIZELLE_SOURCE"], "phone,web_voice")

    def test_phone_only_creation_and_new_email_punctuation_are_preserved(self):
        for lead in [LEAD, {"call_id": "phone-only", "phone": "7869772774", "lead_type": "seller", "channel": "phone"}]:
            creates = []
            def respond(request):
                if request.method == "GET": return httpx.Response(404)
                creates.append(__import__('json').loads(request.content)); return httpx.Response(201, json={"id": 10})
            with self.client(respond) as client:
                self.assertEqual(b.upsert(client, b.payload(lead)), 10)
            self.assertFalse(creates[0]["updateEnabled"]); self.assertFalse(creates[0]["forceMerge"])
            self.assertEqual(creates[0]["listIds"], [30, 31] if lead is LEAD else [31])
            self.assertEqual(creates[0].get("email"), lead.get("email"))
            self.assertTrue(creates[0]["attributes"]["SMS"].startswith("+1"))

    def test_conflicting_identifiers_are_never_merged(self):
        writes = []
        def respond(request):
            if request.method == "GET":
                return httpx.Response(200, json={"id": 1 if request.url.params.get("identifierType") == "email_id" else 2})
            writes.append(request); return httpx.Response(204)
        with self.client(respond) as client, self.assertRaises(b.IdentityConflict):
            b.upsert(client, b.payload(LEAD))
        self.assertFalse(writes)

    def test_blocked_phone_only_contact_is_not_resubscribed_by_email_enrichment(self):
        calls = []
        def respond(request):
            calls.append(request.method)
            if request.url.params.get("identifierType") == "email_id": return httpx.Response(404)
            return httpx.Response(200, json={"id": 1, "emailBlacklisted": True})
        with self.client(respond) as client, self.assertRaises(b.IdentityConflict):
            b.upsert(client, b.payload(LEAD))
        self.assertEqual(calls, ["GET", "GET"])

    def test_lost_create_response_can_be_retried_without_duplicate_creation(self):
        reads = 0; posts = 0
        def respond(request):
            nonlocal reads, posts
            if request.method == "GET":
                reads += 1
                return httpx.Response(404) if reads <= 2 else httpx.Response(200, json={"id": 42, "email": LEAD["email"]})
            if request.method == "POST":
                posts += 1; return httpx.Response(400, json={"code": "duplicate_parameter"})
            return httpx.Response(204)
        with self.client(respond) as client:
            self.assertEqual(b.upsert(client, b.payload(LEAD)), 42)
        self.assertEqual(posts, 1)

    def test_capture_requires_confirmation_before_any_write(self):
        db = MagicMock()
        with self.assertRaises(ValueError):
            capture.capture(db, {"email": "alex@example.com", "lead_types": ["seller"], "summary": "Follow up"},
                            {"call": {"id": str(uuid4()), "assistantId": capture.PHONE_ASSISTANT}})
        db.batch.assert_not_called()
        db.collection.assert_not_called()

    def test_web_voice_capture_requires_consent(self):
        db = MagicMock(); db.collection.return_value.document.return_value.get.return_value.to_dict.return_value = {}
        with self.assertRaises(ValueError):
            capture.capture(db, {"email": "alex@example.com", "email_confirmed": True, "lead_types": ["buyer"], "summary": "Follow up"},
                            {"call": {"id": str(uuid4()), "assistantId": capture.WEB_ASSISTANT, "type": "webCall"}})
        db.collection.return_value.document.return_value.set.assert_not_called()


@unittest.skipUnless(os.getenv("FIRESTORE_EMULATOR_HOST", "").startswith("127.0.0.1:"), "Firestore emulator required")
class DurableSync(unittest.TestCase):
    def setUp(self):
        self.db = firestore.Client(project="demo-receptionist", credentials=AnonymousCredentials())
        self.lead = {**LEAD, "call_id": str(uuid4())}

    def test_replayed_lead_has_one_job_and_one_sync(self):
        first = b.enqueue(self.db, self.lead); second = b.enqueue(self.db, self.lead)
        self.assertEqual(first.path, second.path)
        with patch.object(b, "secret", return_value=b"test"), patch.object(b, "upsert", return_value=123) as send:
            b.sync_job(self.db, first); b.sync_job(self.db, second)
        send.assert_called_once(); self.assertEqual(first.get().get("status"), "synced")

    def test_provider_failure_remains_retryable_and_a_conflict_goes_to_review(self):
        job = b.enqueue(self.db, self.lead)
        with patch.object(b, "secret", return_value=b"test"), patch.object(b, "upsert", side_effect=TimeoutError):
            with self.assertRaises(TimeoutError): b.sync_job(self.db, job)
        self.assertEqual(job.get().get("status"), "pending")
        with patch.object(b, "secret", return_value=b"test"), patch.object(b, "upsert", side_effect=b.IdentityConflict):
            b.sync_job(self.db, job)
        self.assertEqual(job.get().get("status"), "review")

    def test_simultaneous_retry_cannot_start_a_second_worker(self):
        job = b.enqueue(self.db, self.lead); entered, release = Event(), Event()
        def upsert(*args):
            entered.set(); self.assertTrue(release.wait(10)); return 123
        with patch.object(b, "secret", return_value=b"test"), patch.object(b, "upsert", side_effect=upsert) as send, ThreadPoolExecutor() as pool:
            worker = pool.submit(b.sync_job, self.db, job)
            try:
                self.assertTrue(entered.wait(10)); b.sync_job(self.db, job)
            finally: release.set()
            worker.result()
        send.assert_called_once()

    def test_web_text_is_saved_and_retried_without_a_call_ended_event(self):
        sid = str(uuid4()); cid = str(uuid4())
        self.db.collection("web_text_sessions").document(sid).set({"expires_at": datetime.now(UTC)+timedelta(hours=1)})
        message = {"chat": {"id": cid, "assistantId": capture.WEB_ASSISTANT,
            "assistantOverrides": {"variableValues": {"gz_session": sid}},
            "messages": [{"role": "system", "content": "Secret prompt"}, {"role": "user", "content": "Please call me"}]}}
        args = {"email": "alex@example.com", "email_confirmed": True, "lead_types": ["buyer"], "summary": "Follow up"}
        with patch.object(capture.records, "deliver"), patch.object(b, "sync_job"):
            capture.capture(self.db, args, message)
            args.update(email="alex.correct@example.com")
            capture.capture(self.db, args, message)
        record = self.db.collection("leads").document(capture.records.key_for("lead", "webtext:"+sid)).get().to_dict()
        self.assertEqual(record["channel"], "web_text"); self.assertEqual(record["email"], "alex.correct@example.com")
        self.assertNotIn("Secret prompt", record["transcript"])

    def test_superseded_pending_email_is_not_imported_after_correction(self):
        old = b.enqueue(self.db, self.lead)
        new = b.enqueue(self.db, {**self.lead, "email": "correct@example.com"})
        with patch.object(b, "secret", return_value=b"test"), patch.object(b, "upsert", return_value=42) as send:
            b.sync_job(self.db, old); b.sync_job(self.db, new)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[1]["email"], "correct@example.com")
        self.assertEqual(old.get().get("status"), "superseded")

    def test_provider_chat_metadata_and_top_level_assistant_are_supported(self):
        sid = str(uuid4())
        self.db.collection("web_text_sessions").document(sid).set({"expires_at": datetime.now(UTC)+timedelta(hours=1)})
        message = {"assistant": {"id": capture.WEB_ASSISTANT},
            "chat": {"id": str(uuid4()), "metadata": {"variableValues": {"gz_session": sid}}}}
        args = {"email": "alex@example.com", "email_confirmed": True, "lead_types": ["buyer"], "summary": "Follow up"}
        with patch.object(capture.records, "deliver"), patch.object(b, "sync_job"):
            result = capture.capture(self.db, args, message)
        self.assertIn("GZ_INQUIRY_SAVED", result["result"])
