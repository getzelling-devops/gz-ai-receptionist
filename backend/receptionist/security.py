import hashlib
import hmac
import json
import re
import time

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .config import secret


def timestamp_fresh(value, now):
    if not re.fullmatch(r"[0-9]{10}|[0-9]{13}", value):
        return False
    seconds = int(value) / (1000 if len(value) == 13 else 1)
    return abs(now - seconds) <= 300


async def signed_message(request: Request):
    stamp = request.headers.get("x-timestamp", "")
    signature = request.headers.get("x-signature", "")
    if not timestamp_fresh(stamp, time.time()) or not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
        raise HTTPException(401, "Invalid webhook signature")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 8 * 1024 * 1024:
            raise HTTPException(413, "Webhook too large")
        body.extend(chunk)
    key = await run_in_threadpool(secret, "VAPI_HMAC_SECRET", "vapi-webhook-hmac")
    digest = hmac.new(key, stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, signature.lower()):
        raise HTTPException(401, "Invalid webhook signature")
    try:
        envelope = json.loads(body)
        if isinstance(envelope, dict) and isinstance(envelope.get("message"), dict):
            return envelope["message"]
    except (ValueError, UnicodeError):
        pass
    raise HTTPException(422, "Expected a Vapi message")
