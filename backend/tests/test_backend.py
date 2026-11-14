import hashlib
import hmac
import json
import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from receptionist import booking, main, records

KEY = b"unit-test-credential"
REPORT = {"type": "end-of-call-report", "call": {"id": "call-test"},
          "artifact": {"transcript": "Hello", "recording": {"mono": {"combinedUrl": "https://example.test/audio"}},
                       "structuredOutputs": {"uuid": {"name": "getzelling_lead", "result": {
                           "name": "Test", "phone": "+15550100", "lead_type": "seller", "summary": "Listing"}}}}}


def signed(client, route, message, offset=0, tampered=False):
    body = json.dumps({"message": message}).encode()
    stamp = str(int(time.time()) + offset)
    signature = hmac.new(KEY, stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return client.post(route, content=body + (b" " if tampered else b""),
                       headers={"x-timestamp": stamp, "x-signature": signature})


class Contracts(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.enterContext(patch("receptionist.security.secret", return_value=KEY))

    def test_calendar_uses_scoped_short_lived_credential(self):
        with patch.dict(os.environ, BOOKING_CALENDAR_ID="test-calendar", CALENDAR_SERVICE_ACCOUNT="calendar@example.test"), \
                patch.object(booking.google.auth, "default", return_value=(AnonymousCredentials(), None)), \
                patch.object(booking.impersonated_credentials, "Credentials") as mint, \
                patch.object(booking, "AuthorizedSession") as session:
            booking.Calendar()
        options = mint.call_args.kwargs
        self.assertEqual(options["target_principal"], "calendar@example.test")
        self.assertEqual(options["lifetime"], 600)
        self.assertEqual(set(options["target_scopes"]), {
            "https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/calendar.freebusy",
            "https://www.googleapis.com/auth/calendar.calendars.readonly",
        })
        session.assert_called_once_with(mint.return_value)

    def test_reject_unsigned_stale_and_tampered_before_business_logic(self):
        with patch.object(main, "database") as db:
            self.assertEqual(self.client.post("/tools/book-appointment", content=b"{}").status_code, 401)
            for kwargs in ({"offset": -360}, {"offset": 360}, {"tampered": True}):
                self.assertEqual(signed(self.client, "/webhooks/call-ended", REPORT, **kwargs).status_code, 401)
            db.assert_not_called()

    def test_each_tool_receives_own_result(self):
        message = {"type": "tool-calls", "call": {"id": "call-1"}, "toolCallList": [
            {"id": str(i), "function": {"name": name, "arguments": {"date": "2031-04-10"}}}
            for i, name in enumerate(("check-availability", "wrong"))]}
        with patch.object(main, "database"), patch.object(main, "Calendar"), patch.object(
                main, "availability", return_value={"result": "slot"}):
            results = signed(self.client, "/tools/check-availability", message).json()["results"]
        self.assertEqual(results[0], {"toolCallId": "0", "result": "slot"})
        self.assertIn("error", results[1])

    def test_completed_farewell_does_not_depend_on_business_services(self):
        message = {"type": "tool-calls", "call": {"id": "call-ending"}, "toolCallList": [
            {"id": "farewell-1", "function": {"name": "finish-call", "arguments": {}}}]}
        with patch.object(main, "database") as db, patch.object(main, "Calendar") as calendar:
            response = signed(self.client, "/tools/finish-call", message)
        self.assertEqual(response.status_code, 200)
        result = response.json()["results"][0]
        self.assertEqual(result["toolCallId"], "farewell-1")
        self.assertIn("GZ_FAREWELL_COMPLETE", result["result"])
        db.assert_not_called()
        calendar.assert_not_called()

    def test_artifact_and_legacy(self):
        lead = records.extract_lead(REPORT)
        self.assertEqual([lead[k] for k in ("name", "lead_type", "summary", "transcript", "recording_url")],
                         ["Test", "seller", "Listing", "Hello", "https://example.test/audio"])
        lead = records.extract_lead({"call": {"id": "a", "customer": {"number": "123"}},
                                     "recordingUrl": "https://example.test/old", "transcript": "Legacy"})
        self.assertEqual(lead["phone"], "123")
        self.assertEqual(lead["recording_url"], "https://example.test/old")

    def test_explicitly_declined_recording(self):
        report = {**REPORT, "compliance": {"recordingConsent": {"type": "verbal"}}}
        lead = records.extract_lead(report)
        self.assertIsNone(lead["transcript"])
        self.assertIsNone(lead["recording_url"])

    def test_business_hours_and_dst(self):
        zone = booking.MIAMI
        winter = datetime(2030, 1, 7, 17, tzinfo=zone)
        summer = datetime(2030, 7, 8, 17, tzinfo=zone)
        self.assertNotEqual(winter.utcoffset(), summer.utcoffset())
        for start in (winter, summer):
            for hours, status in [(24, "confirmed"), (23, "tentative")]:
                finish, actual = booking.slot_policy(start, "listing_presentation", start - timedelta(hours=hours))
                self.assertEqual((finish.hour, actual), (18, status))
            with self.assertRaises(booking.ToolError):
                booking.slot_policy(start.replace(minute=30), "listing_presentation", start - timedelta(days=2))
        sat = winter + timedelta(days=5)
        self.assertEqual(booking.slot_policy(sat, "first_call", winter)[1], "tentative")
        with self.assertRaises(booking.ToolError):
            booking.parse_start("2030-04-01T10:00:00")


class RequestedAvailability(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.collection.return_value.document.return_value.get.return_value.to_dict.return_value = {}
        self.cal = MagicMock()
        self.cal.id = "test-calendar"
        self.cal.busy.return_value = []
        self.start = datetime(2031, 4, 10, 10, tzinfo=booking.MIAMI)
        self.args = {"date": self.start.date().isoformat(), "start": self.start.isoformat(),
                     "appointment_type": "first_call"}

    def test_requested_time_is_checked_even_when_earlier_slots_are_free(self):
        reply = booking.availability(self.db, self.cal, self.args)
        self.assertIn("Requested slot available: " + self.start.isoformat(), reply["result"])
        self.assertNotIn("T09:00", reply["result"])

    def test_busy_requested_time_requires_agreement_to_later_alternative(self):
        self.cal.busy.return_value = [(self.start, self.start + booking.STEP)]
        reply = booking.availability(self.db, self.cal, self.args)
        self.assertIn("unavailable", reply["error"])
        self.assertIn((self.start + booking.STEP).isoformat(), reply["error"])
        self.assertIn("explicit agreement", reply["error"])

    def test_reserved_requested_time_is_not_offered(self):
        self.db.collection.return_value.document.return_value.get.return_value.to_dict.return_value = {"t1000": "pending-booking"}
        reply = booking.availability(self.db, self.cal, self.args)
        self.assertIn("unavailable", reply["error"])
        self.assertIn((self.start + booking.STEP).isoformat(), reply["error"])

    def test_time_must_match_date_in_miami(self):
        with self.assertRaisesRegex(booking.ToolError, "same Miami day"):
            booking.availability(self.db, self.cal, {**self.args, "start": "2031-04-10T01:00:00+02:00"})


@unittest.skipUnless(os.getenv("FIRESTORE_EMULATOR_HOST", "").startswith("127.0.0.1:"),
                     "set FIRESTORE_EMULATOR_HOST to a loopback emulator")
class Persistence(unittest.TestCase):
    def setUp(self):
        self.db = firestore.Client(project="demo-receptionist", credentials=AnonymousCredentials())
        self.calendar = MagicMock()
        self.calendar.id = uuid4().hex
        self.start = (datetime.now(booking.MIAMI) + timedelta(days=7)).replace(hour=10, minute=0,
                                                                             second=0, microsecond=0)
        self.args = {"start": self.start.isoformat(), "appointment_type": "listing_presentation",
                     "contact_name": "Test", "phone": "5550100"}
        self.calendar.busy.return_value = []
        self.calendar.find.return_value = None
        self.calendar.insert.side_effect = lambda event: event

    def test_overlapping_call_and_replayed_booking(self):
        entered, release = Event(), Event()
        def insert(event):
            entered.set()
            self.assertTrue(release.wait(10))
            return event
        self.calendar.insert.side_effect = insert
        op = uuid4().hex
        other = {**self.args, "start": (self.start + booking.STEP).isoformat(), "appointment_type": "first_call"}
        with ThreadPoolExecutor() as executor:
            first = executor.submit(booking.book, self.db, self.calendar, op, self.args)
            try:
                self.assertTrue(entered.wait(10))
                reply = booking.book(self.db, self.calendar, uuid4().hex, other)
                self.assertIn("Offer", reply["error"])
            finally:
                release.set()
            success = first.result()
        self.assertEqual(success, booking.book(self.db, self.calendar, op, self.args))
        self.calendar.insert.assert_called_once()

    def test_occupied_calendar_returns_alternative(self):
        self.calendar.busy.return_value = [(self.start, self.start + booking.STEP * 2)]
        reply = booking.book(self.db, self.calendar, uuid4().hex, self.args)
        self.assertIn((self.start + booking.STEP * 2).isoformat(), reply["error"])
        self.calendar.insert.assert_not_called()

    def test_ambiguous_calendar_insert(self):
        op = uuid4().hex
        self.calendar.insert.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            booking.book(self.db, self.calendar, op, self.args)
        self.db.collection("bookings").document(op).update({"lease_until": datetime.now(UTC)})
        self.calendar.find.return_value = self.calendar.insert.call_args.args[0]
        self.assertIn("result", booking.book(self.db, self.calendar, op, self.args))
        self.calendar.insert.assert_called_once()

    def test_report_retry_after_email_failure(self):
        message = {**REPORT, "call": {"id": uuid4().hex}}
        client = TestClient(main.app)
        with patch("receptionist.security.secret", return_value=KEY), patch.object(main, "database", return_value=self.db), \
                patch.dict(os.environ, BREVO_SENDER="test@example.test"), patch.object(records, "secret", return_value=KEY), \
                patch.object(records.httpx, "post", side_effect=[httpx.ReadTimeout("lost"), httpx.Response(201)]) as mail:
            self.assertEqual(signed(client, "/webhooks/call-ended", message).status_code, 503)
            lead = self.db.collection("leads").document(records.key_for("lead", message["call"]["id"])).get()
            self.assertEqual(lead.get("transcript"), "Hello")
            self.assertEqual(lead.get("recording_url"), "https://example.test/audio")
            for _ in range(2):
                self.assertEqual(signed(client, "/webhooks/call-ended", message).status_code, 200)
            self.assertEqual(mail.call_count, 2)
            self.assertEqual(mail.call_args_list[0], mail.call_args_list[1])

    def test_urgent_deliveries_are_independent(self):
        handled = []
        operation = uuid4().hex
        def send(db, ref):
            handled.append(ref.get().get("to"))
            if handled[-1] == "support@getzelling.com":
                raise TimeoutError()
        with patch.dict(os.environ, ON_CALL_EMAIL="page@example.test"), patch.object(main, "deliver", side_effect=send):
            for _ in range(2):
                with self.assertRaisesRegex(booking.ToolError, "transfer"):
                    main.escalate(self.db, operation, {"message": "Urgent callback"})
        self.assertEqual(handled, ["support@getzelling.com", "page@example.test"] * 2)
