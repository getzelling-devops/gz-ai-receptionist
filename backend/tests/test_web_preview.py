import json
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from receptionist import web_preview as web


class ConsentGate(unittest.TestCase):
    def setUp(self):
        self.session = uuid4()
        self.value = web.Consent(session=self.session, accepted=True, version=web.DISCLOSURE,
                                 language="es", history=[])
        self.db = MagicMock()
        self.enterContext(patch.object(web, "clients", return_value=(self.db, None)))
        self.provider = self.enterContext(patch.object(web, "provider"))
        self.enterContext(patch.object(web.firestore, "transactional", side_effect=lambda f: f))
        self.grant = self.db.collection.return_value.document.return_value

    def test_decline_wrong_version_and_non_boolean(self):
        with self.assertRaises(HTTPException):
            web.consent(self.value.model_copy(update={"accepted": False}))
        for changes in ({"accepted": "true"}, {"accepted": 1}, {"version": "old"}):
            with self.assertRaises(ValidationError):
                web.Consent.model_validate({**self.value.model_dump(), **changes})
        self.db.collection.assert_not_called()
        self.provider.assert_not_called()

    def test_grant_precedes_provider_and_rejects_replay(self):
        ticket = web.consent(self.value)["ticket"]
        self.provider.assert_not_called()
        audit = self.grant.create.call_args.args[0]
        self.assertTrue(audit["accepted"])
        self.assertEqual(audit["granted_at"], web.firestore.SERVER_TIMESTAMP)
        join = web.Join(session=self.session, ticket=ticket)
        for changes in ({"session_id": str(uuid4())}, {"used_at": datetime.now(UTC)},
                        {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}):
            self.grant.get.return_value.to_dict.return_value = {**audit, **changes}
            with self.assertRaises(HTTPException):
                web.voice(join)
        self.provider.assert_not_called()
        self.grant.get.return_value.to_dict.return_value = audit
        def room(path, body):
            self.db.transaction.return_value.update.assert_called_once()
            self.assertEqual(path, "call/web")
            self.assertEqual(body["assistantId"], web.ASSISTANT_ID)
            self.assertNotIn("server", body["assistantOverrides"])
            return {"id": str(uuid4()), "transport": {"callUrl": "https://example.test/room"}}
        self.provider.side_effect = room
        self.assertEqual(web.voice(join)["webCallUrl"], "https://example.test/room")
        self.db.batch.return_value.commit.assert_called_once()


class WebsiteMarketEvidence(unittest.TestCase):
    def test_only_reviewed_excerpts_reach_web_conversations(self):
        from receptionist.web_market import PILOT
        visitor = web.Session(session=uuid4(), language="es", history=[])
        supplied = json.loads(web.overrides(visitor)["variableValues"]["gz_market"])
        review = json.loads((PILOT / "source-review.json").read_text())
        checked = [e for e in review["entries"] if e["decision"] == "retain_checked_excerpt"]
        self.assertCountEqual(supplied["articles"], [
            {"published": e["checked_publication_date"], "excerpt": e["retained_excerpt"]}
            for e in checked])
        manifest = json.loads((PILOT / "source-reviewed-staging-receipt.json").read_text())
        self.assertEqual(supplied["through"], manifest["coverage_end"])
        phone = (PILOT.parents[1] / "receptionist" / "phone_assistant.json").read_text()
        self.assertNotIn("gz_market", phone)
        self.assertIn("this is Gizelle", json.loads(phone)["firstMessage"])


class CompanyQuestionsFromNews(unittest.TestCase):
    def test_company_questions_in_both_languages_bypass_news_only_response(self):
        for question in ("I am interested in your GetZelling services", "¿Qué servicios ofrece GetZelling?"):
            with self.subTest(question=question), patch.object(web, "clients", return_value=(MagicMock(), None)), \
                    patch.object(web.httpx, "Client") as news, \
                    patch.object(web, "provider", return_value={"id": str(uuid4()),
                        "output": [{"role": "assistant", "content": "We help sellers."}]}) as provider:
                value = web.Chat(session=uuid4(), language="en", history=[], topic="news", question=question)
                self.assertEqual(web.chat(value)["answer"], "We help sellers.")
                news.assert_not_called()
                self.assertEqual(provider.call_args.args[0], "chat")


class UnifiedWebsiteChat(unittest.TestCase):
    def test_historical_question_retrieves_citations_without_a_topic_choice(self):
        response = MagicMock()
        citation = {"id": "checked-article", "url": "https://publisher.example/article"}
        response.json.return_value = {"intent": "historical", "answer": "Dated evidence.",
                                      "citations": [citation]}
        with patch.object(web, "search_market", return_value=response.json.return_value), patch.object(web, "provider") as provider:
            value = web.Chat(session=uuid4(), language="en", history=[],
                             question="What do GetZelling’s Market insights say about Miami condos in July 2025?")
            result = web.chat(value)
            self.assertEqual(result["citations"], [citation])
            self.assertEqual(result["answer"], "Dated evidence.")
            provider.assert_not_called()

    def test_failed_capture_cannot_be_presented_as_success_in_either_language(self):
        for language in ("en", "es"):
            for marker in ("GZ_INQUIRY_NOT_SAVED", "GZ_INQUIRY_SAVED"):
                output = [
                    {"role": "assistant", "tool_calls": [{"id": "capture", "function": {"name": "capture-lead"}}]},
                    {"role": "tool", "tool_call_id": "capture", "content": marker},
                    {"role": "assistant", "content": "Your inquiry is saved."},
                ]
                with patch.object(web, "clients", return_value=(MagicMock(), None)), patch.object(web, "provider", return_value={"id": str(uuid4()), "output": output}):
                    result = web.chat(web.Chat(session=uuid4(), language=language, history=[], question="My email is confirmed; please contact me."))
                if marker == "GZ_INQUIRY_SAVED":
                    self.assertEqual(result["answer"], "Your inquiry is saved.")
                else:
                    self.assertIn("haven't saved" if language == "en" else "no he guardado", result["answer"])
