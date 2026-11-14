import json
import os
import time
import hmac
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from receptionist.main import app
from receptionist import telephony

ROOT = "https://receptionist.test"
CALL = "CA" + "a" * 32
TOKEN = "test-twilio-token"
HMAC_KEY = b"vapi-test-key"
GATE = "gzgate_" + "d" * 48


class PhoneFlow(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.enterContext(patch.dict(os.environ, {
            "PUBLIC_BASE_URL": ROOT, "TWILIO_ACCOUNT_SID": "ACtest",
            "TWILIO_PHONE_NUMBER": "+17869772774",
            "VAPI_ASSISTANT_ID": "assistant-test", "VAPI_SIP_URI": "sip:test@sip.vapi.ai",
        }))
        self.enterContext(patch.object(telephony, "secret", return_value=TOKEN.encode()))
        self.db = MagicMock()
        self.enterContext(patch.object(telephony, "database", return_value=self.db))
        self.enterContext(patch.object(telephony.firestore, "transactional", side_effect=lambda fn: fn))
        self.form = {"AccountSid": "ACtest", "CallSid": CALL, "To": "+17869772774", "From": "+12025550142"}
        self.ref = self.db.collection.return_value.document.return_value
        self.snap = self.ref.get.return_value

    def post(self, path, form=None):
        form = self.form if form is None else form
        sig = RequestValidator(TOKEN).compute_signature(ROOT + path, form)
        return self.client.post(path, data=form, headers={"x-twilio-signature": sig})

    def resolve(self, gate=GATE, call="vapi-a"):
        message = {"type": "assistant-request", "call": {"id": call,
                    "assistantOverrides": {"variableValues": {"gzgate": gate}}}}
        raw = json.dumps({"message": message}).encode()
        stamp = str(int(time.time()))
        with patch("receptionist.security.secret", return_value=HMAC_KEY):
            return self.client.post("/telephony/vapi/resolve", content=raw, headers={
                "x-timestamp": stamp, "x-signature": hmac.digest(HMAC_KEY, stamp.encode()+b"."+raw, "sha256").hex()
            })

    def test_unsigned_and_altered_twilio_requests_cannot_issue_gate(self):
        result = self.client.post("/telephony/twilio/connect", data=self.form)
        self.assertEqual(result.status_code, 401)
        self.db.transaction.assert_not_called()
        sig = RequestValidator(TOKEN).compute_signature(ROOT + "/telephony/twilio/connect", self.form)
        result = self.client.post("/telephony/twilio/connect", data={**self.form, "To": "+12025550143"},
                                  headers={"x-twilio-signature": sig})
        self.assertEqual(result.status_code, 401)

    def test_notice_contains_no_dial_or_recording_and_pauses_before_redirect(self):
        self.snap.exists = False
        root = ET.fromstring(self.post("/telephony/twilio/inbound").text)
        self.assertEqual([e.tag for e in root], ["Say", "Say", "Pause", "Redirect"])
        self.assertEqual(root.find("Pause").attrib["length"], "3")
        self.assertIn("consent", root.find("Say").text)
        self.assertIn("es", root.findall("Say")[1].attrib["language"])
        self.db.transaction.return_value.create.assert_called_once()

    def test_missing_notice_and_too_early_connect_fail_closed(self):
        for record in (None, {"notice_started_at": datetime.now(UTC)}):
            self.snap.to_dict.return_value = record
            root = ET.fromstring(self.post("/telephony/twilio/connect").text)
            self.assertIsNone(root.find("Dial"))
            self.assertIsNotNone(root.find("Hangup"))

    def test_continuation_issues_expiring_gate_and_turns_off_twilio_recording(self):
        self.snap.to_dict.return_value = {
            "notice_started_at": datetime.now(UTC)-timedelta(minutes=1),
            "disclosure_version": "notice-before-deployment",
        }
        root = ET.fromstring(self.post("/telephony/twilio/connect").text)
        dial = root.find("Dial")
        self.assertEqual(dial.attrib["record"], "do-not-record")
        self.assertIn("X-gzgate=gzgate_", dial.find("Sip").text)
        payload = self.db.transaction.return_value.create.call_args.args[1]
        self.assertLess(payload["expires_at"], datetime.now(UTC)+timedelta(minutes=3))
        self.assertEqual(payload["disclosure_version"], "notice-before-deployment")

    def test_unknown_expired_or_consumed_gate_never_returns_assistant(self):
        for record in (None, {"expires_at": datetime.now(UTC)-timedelta(seconds=1)},
                       {"expires_at": datetime.now(UTC)+timedelta(minutes=1), "vapi_call_id": "other"}):
            self.snap.to_dict.return_value = record
            self.assertIn("error", self.resolve().json())
        self.assertIn("error", self.resolve(gate="missing").json())

    def test_authorized_session_has_gizelle_greeting_and_replays_only_for_same_call(self):
        self.snap.to_dict.return_value = {
            "expires_at": datetime.now(UTC)+timedelta(minutes=1), "vapi_call_id": "vapi-a",
            "twilio_call_id": CALL, "continued_at": datetime.now(UTC),
            "disclosure_version": telephony.DISCLOSURE_VERSION,
        }
        result = self.resolve().json()
        self.assertEqual(result["assistantId"], "assistant-test")
        override = result["assistantOverrides"]
        self.assertEqual(override["firstMessage"],
                         "Thank you for calling GetZelling, this is Gizelle, how can I help you today?")
        self.assertTrue(override["artifactPlan"]["recordingEnabled"])
        self.assertFalse(override.get("compliancePlan", {}).get("recordingConsentPlan"))
