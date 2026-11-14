"""Separate Cloud Run entrypoint. Staging MUST retain Cloud Run IAM enforcement."""
import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .news import news_service

app = FastAPI(title="GetZelling news preview", docs_url=None, redoc_url=None, openapi_url=None)
log = logging.getLogger(__name__)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)


@app.get("/health")
def health():
    return {"service": "getzelling-news", "provider": "vertex"}


@app.post("/chat")
def chat(value: Question):
    if not value.question.strip():
        raise HTTPException(422, "Enter a question")
    try:
        return news_service().answer(value.question.strip())
    except Exception as exc:
        # Provider response bodies can include source text and visitor questions.
        log.error("News request failed (%s)", type(exc).__name__)
        raise HTTPException(503, "The news archive is temporarily unavailable. Please try again.") from None
