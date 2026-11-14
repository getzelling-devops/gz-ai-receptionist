import copy
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from receptionist.news import News, QueryPlan, safe_source, validate_corpus
from receptionist.news_app import app
from receptionist.vertex import Vertex, VertexSettings


CORPUS = "a" * 64
META = {"state": "ready", "visibility": "private_review", "public_retrieval_allowed": False,
        "embedding_model": "gemini-embedding-001", "embedding_dimensions": 768,
        "chunk_count": 2, "coverage_end": "2025-10-26"}
ROW = {"corpus_id": CORPUS, "article_id": "older-condos", "title": "Older Miami condos",
       "original_url": "https://publisher.example/2025/07/23/older-condos",
       "publisher": "Example publisher", "publication_date": "2025-07-23",
       "digest_start": "2025-07-21", "digest_end": "2025-07-27",
       "text": "The archived digest discusses older condos.", "review_status": "needs_source_verification",
       "public_retrieval_allowed": False}
PLAN = {"language": "en", "intent": "historical", "search_query": "older Miami condos July 2025",
        "publication_start": "2025-07-01", "publication_end": "2025-07-31"}
ANSWER = {"answer": "The July 2025 digest discusses older condos [1].",
          "citation_ids": ["older-condos"], "insufficient_evidence": False}


class NewsContracts(unittest.TestCase):
    def service(self, plan=None, answer=None, rows=None, metadata=None, review=True):
        db = MagicMock()
        ref = db.collection.return_value.document.return_value
        ref.get.return_value.to_dict.return_value = copy.deepcopy(META if metadata is None else metadata)
        nearest = ref.collection.return_value.find_nearest.return_value
        docs = []
        for row in ([ROW] if rows is None else rows):
            doc = MagicMock()
            doc.to_dict.return_value = copy.deepcopy(row)
            docs.append(doc)
        nearest.stream.return_value = iter(docs)
        vertex = MagicMock()
        vertex.settings = VertexSettings()
        vertex.structured.side_effect = [copy.deepcopy(plan or PLAN), copy.deepcopy(answer or ANSWER)]
        vertex.embed.return_value = [0.1] * 768
        return News(db, vertex, CORPUS, review_mode=review), ref, vertex

    def test_keyless_client_uses_explicit_credentials_and_no_api_key(self):
        creds = object()
        with patch("receptionist.vertex.genai.Client") as client:
            Vertex(credentials=creds)
        self.assertTrue(client.call_args.kwargs["vertexai"])
        self.assertIs(client.call_args.kwargs["credentials"], creds)
        self.assertNotIn("api_key", client.call_args.kwargs)

    def test_private_corpus_is_rejected_by_public_mode_before_model_call(self):
        service, _, vertex = self.service(review=False)
        with self.assertRaisesRegex(ValueError, "visibility"):
            service.answer("July condos")
        vertex.structured.assert_not_called()

    def test_unready_and_incompatible_embedding_corpora_are_rejected(self):
        for update in ({"state": "building"}, {"embedding_model": "another-model"},
                       {"embedding_dimensions": 3072}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_corpus({**META, **update}, VertexSettings(), True)

    def test_current_spanish_question_abstains_without_vector_search(self):
        service, ref, vertex = self.service(plan={**PLAN, "language": "es", "intent": "current"})
        result = service.answer("¿Cómo está el mercado hoy?")
        self.assertIn("información histórica", result["answer"])
        self.assertEqual(result["citations"], [])
        vertex.embed.assert_not_called()
        ref.collection.assert_not_called()

    def test_avn_private_and_injection_requests_have_no_retrieval(self):
        for intent in ("avn", "private", "unsafe", "valuation"):
            with self.subTest(intent=intent):
                service, ref, vertex = self.service(plan={**PLAN, "intent": intent})
                self.assertEqual(service.answer("question")["citations"], [])
                vertex.embed.assert_not_called()
                ref.collection.assert_not_called()

    def test_historical_response_keeps_real_article_date_and_review_status(self):
        service, _, _ = self.service()
        result = service.answer("July 2025 condos")
        self.assertEqual(result["citations"][0]["published_at"], "2025-07-23")
        self.assertEqual(result["citations"][0]["digest_start"], "2025-07-21")
        self.assertFalse(result["citations"][0]["source_verified"])
        self.assertTrue(result["review_only"])

    def test_date_filter_and_duplicate_chunk_do_not_hide_in_period_article(self):
        rows = [{**ROW, "article_id": "newer", "publication_date": "2025-10-23"}, ROW, ROW]
        service, _, vertex = self.service(rows=rows)
        result = service.answer("July 2025 condos")
        self.assertEqual([c["id"] for c in result["citations"]], ["older-condos"])
        evidence = vertex.structured.call_args.args[1]["excerpts"]
        self.assertEqual(len(evidence), 1)

    def test_nonmatching_date_returns_no_claims_and_no_generation(self):
        service, _, vertex = self.service(rows=[{**ROW, "publication_date": "2025-10-23"}])
        self.assertEqual(service.answer("July 2025 condos")["citations"], [])
        self.assertEqual(vertex.structured.call_count, 1)

    def test_answers_cannot_invent_citations_or_urls(self):
        for update in ({"citation_ids": ["invented"]}, {"answer": "Claim [7]."},
                       {"citation_ids": []}, {"answer": "Read https://untrusted.example [1]."}):
            with self.subTest(update=update):
                service, _, _ = self.service(answer={**ANSWER, **update})
                with self.assertRaises(ValueError):
                    service.answer("July 2025 condos")

    def test_retrieval_cannot_cross_the_pinned_corpus(self):
        service, _, _ = self.service(rows=[{**ROW, "corpus_id": "b" * 64}])
        with self.assertRaisesRegex(ValueError, "corpus"):
            service.answer("July 2025 condos")

    def test_public_mode_requires_per_article_source_approval(self):
        meta = {**META, "visibility": "approved_public", "public_retrieval_allowed": True}
        service, _, vertex = self.service(review=False, metadata=meta)
        self.assertEqual(service.answer("July 2025 condos")["citations"], [])
        self.assertEqual(vertex.structured.call_count, 1)

    def test_invalid_citation_link_and_reversed_dates_are_rejected(self):
        with self.assertRaises(ValueError):
            safe_source({**ROW, "original_url": "javascript:alert(1)"})
        with self.assertRaises(ValueError):
            QueryPlan.model_validate({**PLAN, "publication_end": "2025-06-01"})

    def test_api_rejects_invalid_questions_before_inference_and_masks_provider_errors(self):
        client = TestClient(app)
        with patch("receptionist.news_app.news_service") as factory:
            for payload in ({"question": " "}, {"question": "x" * 2001},
                            {"question": "test", "collection": "leads"}):
                self.assertEqual(client.post("/chat", json=payload).status_code, 422)
            factory.assert_not_called()
            factory.return_value.answer.side_effect = RuntimeError("private provider details")
            response = client.post("/chat", json={"question": "July 2025 condos"})
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("private provider details", response.text)


if __name__ == "__main__":
    unittest.main()
