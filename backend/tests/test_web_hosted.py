"""Hosted visitor and Vapi boundaries must guard inference before any model call."""
import hashlib
import hmac
import json
import time
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from receptionist import web_app as web


class HostedBoundary(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(web.app)
        self.db = MagicMock()
        self.enterContext(patch.object(web.service, "clients", return_value=(self.db, MagicMock())))
        self.infer = self.enterContext(patch.object(web.service, "chat", return_value={"answer": "Company reply"}))
        self.limit = self.enterContext(patch.object(web, "limit"))
        self.session = str(uuid4())
        self.ref = self.db.collection.return_value.document.return_value

    def test_visitor_session_cannot_be_forged_by_body(self):
        body = {"session": self.session, "language": "en", "history": [], "question": "Services"}
        self.assertEqual(self.client.post("/chat", json=body).status_code, 401)
        self.infer.assert_not_called()
        self.ref.get.return_value.to_dict.return_value = {
            "session_id": self.session, "expires_at": datetime.now(UTC) + timedelta(hours=1)}
        headers = {"Authorization": "Bearer valid-session"}
        self.assertEqual(self.client.post("/chat", json=body, headers=headers).status_code, 200)
        body["session"] = str(uuid4())
        self.assertEqual(self.client.post("/chat", json=body, headers=headers).status_code, 403)
        self.assertEqual(self.infer.call_count, 1)

    def test_voice_has_no_room_without_saved_consent(self):
        self.ref.get.return_value.to_dict.return_value = {
            "session_id": self.session, "expires_at": datetime.now(UTC) + timedelta(hours=1)}
        with patch.object(web.service, "voice") as voice:
            reply = self.client.post("/voice", json={"assistantId": self.session},
                                     headers={"Authorization": "Bearer valid-session"})
            self.assertEqual(reply.status_code, 403)
            voice.assert_not_called()

    def test_signed_market_tool_uses_shared_service_and_rejects_phone_assistant(self):
        key = b"test-webhook-key"
        message = {"type": "tool-calls", "call": {"id": str(uuid4()),
            "assistantId": web.service.ASSISTANT_ID, "type": "webCall"},
            "toolCallList": [{"id": "lookup", "function": {"name": "market-insights",
                "arguments": {"question": "October 2025 Fisher Island"}}}]}
        self.ref.get.return_value.to_dict.return_value = {"accepted": True}
        def send():
            body = json.dumps({"message": message}).encode()
            stamp = str(int(time.time()))
            signature = hmac.new(key, stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
            return self.client.post("/tools/market-insights", content=body,
                headers={"content-type": "application/json", "x-timestamp": stamp, "x-signature": signature})
        result = {"answer": "Historical evidence.", "citations": [], "corpus_id": "pin"}
        with patch("receptionist.security.secret", return_value=key), patch.object(web, "search", return_value=result) as search:
            self.assertEqual(self.client.post("/tools/market-insights", json={"message": message}).status_code, 401)
            self.assertEqual(send().json()["results"][0]["toolCallId"], "lookup")
            search.assert_called_once_with("October 2025 Fisher Island")
            message["call"]["assistantId"] = "telephone-assistant"
            self.assertEqual(send().status_code, 403)
            self.assertEqual(search.call_count, 1)

    def test_oversized_body_cannot_reach_provider(self):
        self.assertEqual(self.client.post("/chat", content=b"x" * 140001).status_code, 413)
        self.infer.assert_not_called()
