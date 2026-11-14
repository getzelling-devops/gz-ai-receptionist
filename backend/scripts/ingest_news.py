"""Publish a pinned PRIVATE review corpus. No customer approval is inferred."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from google.api_core.exceptions import PreconditionFailed
from google.cloud import firestore, storage
from google.cloud.firestore_v1.vector import Vector
from google.oauth2.credentials import Credentials

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from receptionist.vertex import Vertex


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def chunks(article):
    body = "\n".join(x for x in (article.get("summary"), article.get("key_findings")) if x)
    if not body:
        # Older digests contain only a deep-dive summary. It remains unverified.
        body = article.get("narrative_commentary") or ""
    if not body.strip():
        raise ValueError("An article has no extractable evidence")
    prefix = article["title"] + "\n"
    for offset in range(0, len(body), 3700):
        yield prefix + body[offset:offset + 4000]


def reviewed_articles(source, selected, audit, source_hash):
    """Apply a complete, hash-bound review without editing the original digests."""
    entries = audit.get("entries", [])
    decisions = {row["article_id"]: row for row in entries}
    if (audit.get("source_sha256") != source_hash or len(decisions) != len(entries)
            or set(decisions) != selected):
        raise ValueError("Review must cover the exact selected source snapshot")
    articles, excluded = [], []
    for original in source["articles"]:
        if original["id"] not in selected:
            continue
        row = decisions[original["id"]]
        if row["decision"] == "exclude_pending_evidence":
            excluded.append(original["id"])
            continue
        if row["decision"] != "retain_checked_excerpt" or not row.get("retained_excerpt", "").strip():
            raise ValueError("Unknown or empty review decision")
        # No unchecked summary, findings or narrative can leak into embeddings.
        a = copy.deepcopy(original)
        a.update(summary=row["retained_excerpt"], key_findings=None, narrative_commentary=None,
                 title=row["checked_title"], original_url=row["checked_url"],
                 review_status="source_verified", source_verification_scope="retained_excerpt",
                 quality_flags=["source_checked_excerpt_only", "original_narrative_excluded"],
                 publication={"value": row["checked_publication_date"], "precision": "day", "verified": True})
        from datetime import date
        from urllib.parse import urlsplit
        date.fromisoformat(a["publication"]["value"])
        url = urlsplit(a["original_url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Invalid reviewed source URL")
        a["public_retrieval_allowed"] = False
        articles.append(a)
    if len(articles) + len(excluded) != len(selected) or not articles:
        raise ValueError("Review source records are missing or empty")
    return articles, excluded


def archive(bucket, name, body):
    digest = hashlib.sha256(body).hexdigest()
    blob = bucket.blob(name)
    blob.metadata = {"sha256": digest}
    try:
        blob.upload_from_string(body, content_type="application/json", if_generation_match=0)
    except PreconditionFailed:
        existing = bucket.blob(name)
        existing.reload()
        if (existing.metadata or {}).get("sha256") != digest:
            raise ValueError("Immutable source snapshot does not match") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--pilot", type=Path, default=Path("knowledge/news-pilot"))
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--review-audit", type=Path, help="Complete source-bound review; excluded articles are not embedded")
    parser.add_argument("--gcloud-user", action="store_true", help="Use the operator's current CLI token in memory")
    args = parser.parse_args()
    credentials = None
    if args.gcloud_user:
        credentials = Credentials(subprocess.check_output(
            ["gcloud", "auth", "print-access-token"]).decode().strip())
    vertex = Vertex(credentials=credentials)
    database = os.getenv("NEWS_DATABASE", "news-rag-staging")
    if not database.startswith("news-"):
        raise ValueError("Ingestion requires a separate news database")
    db = firestore.Client(project=vertex.settings.project, database=database, credentials=credentials)
    client = storage.Client(project=vertex.settings.project, credentials=credentials)
    bucket = client.bucket(os.getenv("NEWS_SOURCE_BUCKET", "gz-ai-receptionist-news-staging"))
    source = json.loads((args.pilot / "articles.json").read_text())
    selected = {a["article_id"] for a in json.loads((args.pilot / "selection.json").read_text())["articles"]}
    fatal = {"political_timeline_claim_requires_verification", "missing_or_invalid_original_url",
             "url_year_conflicts_with_digest_context"}
    quarantined = []
    articles = []
    for a in source["articles"]:
        if a["id"] not in selected:
            continue
        if fatal.intersection(a["quality_flags"]):
            quarantined.append(a["id"])
            continue
        if a["publication"]["precision"] != "day":
            raise ValueError("Pilot article requires an explicit publication day")
        articles.append(a)
    source_hash = hashlib.sha256((args.pilot / "articles.json").read_bytes()).hexdigest()
    if args.review_audit:
        articles, quarantined = reviewed_articles(source, selected,
            json.loads(args.review_audit.read_text()), source_hash)
    pins = {"format": 1, "visibility": "private_review", "public_retrieval_allowed": False,
            "embedding_model": vertex.settings.embedding_model,
            "embedding_dimensions": vertex.settings.dimensions,
            "source_hash": source_hash,
            "article_ids": [a["id"] for a in articles], "quarantined_article_ids": quarantined}
    if args.review_audit:
        pins.update(format=2, evidence_status="source_checked_excerpts",
                    review_hash=hashlib.sha256(args.review_audit.read_bytes()).hexdigest())
    corpus_id = hashlib.sha256(encoded(pins)).hexdigest()
    ref = db.collection("corpora").document(corpus_id)
    jobs = [(a, i, text) for a in articles for i, text in enumerate(chunks(a))]
    metadata = {**pins, "corpus_id": corpus_id, "article_count": len(articles),
                "chunk_count": len(jobs), "coverage_start": min(a["digest_period"]["start"] for a in articles),
                "coverage_end": max(a["digest_period"]["end"] for a in articles),
                "source_bucket": bucket.name, "state": "building"}
    prior = ref.get().to_dict()
    if prior and prior.get("state") == "ready":
        if any(prior.get(k) != v for k, v in pins.items()):
            raise ValueError("Pinned corpus metadata changed")
        args.receipt.write_text(json.dumps(prior, indent=2, default=str) + "\n")
        print("Reused ready corpus", corpus_id, flush=True)
        vertex.close()
        return
    archive(bucket, f"corpora/{corpus_id}/manifest.json", encoded(pins))
    if args.review_audit:
        archive(bucket, f"corpora/{corpus_id}/source-review.json", args.review_audit.read_bytes())
    for doc_id in sorted({a["source_document_id"] for a in articles}):
        capture = args.captures / (doc_id + ".json")
        archive(bucket, f"corpora/{corpus_id}/sources/{doc_id}.json", capture.read_bytes())
    archive(bucket, f"corpora/{corpus_id}/normalized-articles.json", encoded(articles))
    ref.set(metadata)
    try:
        for a, number, text in jobs:
            chunk_id = a["id"] + "-" + str(number)
            chunk = ref.collection("news_articles").document(chunk_id)
            text_hash = hashlib.sha256(text.encode()).hexdigest()
            previous = chunk.get().to_dict()
            if previous:
                if previous.get("text_sha256") != text_hash or previous.get("corpus_id") != corpus_id:
                    raise ValueError("Existing chunk does not match its pinned source")
                continue
            embedding = vertex.embed(text, document=True, title=a["title"])
            chunk.create({"corpus_id": corpus_id, "article_id": a["id"], "title": a["title"],
                          "publisher": a["publisher"], "original_url": a["original_url"],
                          "publication_date": a["publication"]["value"],
                          "digest_start": a["digest_period"]["start"], "digest_end": a["digest_period"]["end"],
                          "review_status": a["review_status"], "public_retrieval_allowed": False,
                          "quality_flags": a["quality_flags"], "text": text, "text_sha256": text_hash,
                          "embedding": Vector(embedding)})
            print("Embedded", chunk_id, flush=True)
        actual = list(ref.collection("news_articles").stream())
        if len(actual) != len(jobs):
            raise ValueError("Chunk count does not match the manifest")
        ref.update({"state": "ready"})
        metadata["state"] = "ready"
        args.receipt.write_text(json.dumps(metadata, indent=2) + "\n")
        print("Ready PRIVATE review corpus", corpus_id, len(articles), "articles", len(jobs), "chunks", flush=True)
        print("Quarantined", quarantined, flush=True)
    finally:
        vertex.close()
        client.close()


if __name__ == "__main__":
    main()
