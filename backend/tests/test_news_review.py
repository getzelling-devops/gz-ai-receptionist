"""Source review must replace evidence, preserve originals and fail closed."""
import copy
import json
from pathlib import Path
import unittest

from scripts.ingest_news import chunks, reviewed_articles


class SourceReview(unittest.TestCase):
    def fixture(self):
        source = {"articles": [{"id": "keep", "title": "Old title", "summary": "unchecked",
            "key_findings": "unchecked figures", "narrative_commentary": "unchecked narrative"},
            {"id": "exclude", "summary": "must never enter retrieval"}]}
        audit = {"source_sha256": "hash", "entries": [
            {"article_id": "keep", "decision": "retain_checked_excerpt", "retained_excerpt": "Checked facts only.",
             "checked_title": "Corrected title", "checked_url": "https://publisher.example/article",
             "checked_publication_date": "2025-10-18"},
            {"article_id": "exclude", "decision": "exclude_pending_evidence"}]}
        return source, audit

    def test_only_checked_excerpt_is_embedded_without_mutating_original(self):
        source, audit = self.fixture()
        original = copy.deepcopy(source)
        kept, excluded = reviewed_articles(source, {"keep", "exclude"}, audit, "hash")
        self.assertEqual(source, original)
        self.assertEqual(excluded, ["exclude"])
        self.assertEqual(list(chunks(kept[0])), ["Corrected title\nChecked facts only."])
        self.assertEqual(kept[0]["publication"]["value"], "2025-10-18")
        self.assertFalse(kept[0]["public_retrieval_allowed"])

    def test_stale_incomplete_duplicate_or_empty_audits_are_rejected(self):
        for mutation in ("hash", "missing", "duplicate", "empty", "unsafe_url"):
            source, audit = self.fixture()
            if mutation == "hash": audit["source_sha256"] = "stale"
            if mutation == "missing": audit["entries"].pop()
            if mutation == "duplicate": audit["entries"].append(audit["entries"][0])
            if mutation == "empty": audit["entries"][0]["retained_excerpt"] = " "
            if mutation == "unsafe_url": audit["entries"][0]["checked_url"] = "javascript:alert(1)"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                reviewed_articles(source, {"keep", "exclude"}, audit, "hash")

    def test_actual_review_accounts_for_every_selected_candidate(self):
        import hashlib
        root = Path(__file__).resolve().parents[1] / "knowledge/news-pilot"
        raw = (root / "articles.json").read_bytes()
        selected = {a["article_id"] for a in json.loads((root / "selection.json").read_text())["articles"]}
        audit = json.loads((root / "source-review.json").read_text())
        kept, excluded = reviewed_articles(json.loads(raw), selected, audit, hashlib.sha256(raw).hexdigest())
        self.assertEqual((len(kept), len(excluded)), (15, 15))
        self.assertTrue(all(a["narrative_commentary"] is None for a in kept))
        calta = next(a for a in kept if a["id"] == "news-20251020-20251026-14")
        self.assertIn("499 apartments", calta["summary"])
        self.assertNotIn("299", calta["summary"])


if __name__ == "__main__":
    unittest.main()
