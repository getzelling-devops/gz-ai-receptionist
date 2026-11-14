"""Shared authenticated retrieval client for web text and Vapi tools."""
import os
from functools import lru_cache
from time import monotonic

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import id_token


@lru_cache(maxsize=2)
def identity(audience, window):
    return id_token.fetch_id_token(Request(), audience)


def search(question):
    base = os.getenv("NEWS_SERVICE_URL", "http://127.0.0.1:8088").rstrip("/")
    headers = {}
    if base.startswith("https://"):
        headers["Authorization"] = "Bearer " + identity(base, int(monotonic() // 240))
    elif base != "http://127.0.0.1:8088":
        raise ValueError("Invalid news service")
    response = httpx.post(base + "/chat", json={"question": question}, headers=headers, timeout=65)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data.get("answer"), str) or not isinstance(data.get("citations"), list):
        raise ValueError("Invalid market response")
    data["answer"] = data["answer"].replace("this archive", "Market insights").replace("este archivo", "Market insights")
    return data
