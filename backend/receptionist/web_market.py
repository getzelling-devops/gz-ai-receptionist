"""Bounded historical evidence for the operator's private website assistant."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

PILOT = Path(__file__).resolve().parents[1] / "knowledge" / "news-pilot"


@lru_cache(maxsize=1)
def reviewed_market_context():
    manifest = json.loads((PILOT / "source-reviewed-staging-receipt.json").read_text())
    audit = (PILOT / "source-review.json").read_bytes()
    if (manifest["state"] != "ready" or manifest["visibility"] != "private_review"
            or manifest["evidence_status"] != "source_checked_excerpts"
            or hashlib.sha256(audit).hexdigest() != manifest["review_hash"]):
        raise ValueError("Private archive review does not match its manifest")
    articles = {}
    for row in json.loads(audit)["entries"]:
        if row["decision"] == "retain_checked_excerpt":
            articles[row["article_id"]] = {"published": row["checked_publication_date"],
                                           "excerpt": row["retained_excerpt"]}
    if sorted(articles) != sorted(manifest["article_ids"]):
        raise ValueError("Reviewed excerpt inventory mismatch")
    return json.dumps({"through": manifest["coverage_end"], "articles": list(articles.values())},
                      ensure_ascii=False)
