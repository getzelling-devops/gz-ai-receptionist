"""All news-model access uses Vertex and explicit Application Default Credentials."""
import json
import math
import os
from dataclasses import dataclass

import google.auth
from google import genai
from google.genai import types


@dataclass(frozen=True)
class VertexSettings:
    project: str = "gz-ai-receptionist"
    location: str = "global"
    chat_model: str = "gemini-3.1-flash-lite"
    embedding_model: str = "gemini-embedding-001"
    dimensions: int = 768

    @classmethod
    def from_env(cls):
        if os.getenv("NEWS_AI_PROVIDER", "vertex") != "vertex":
            raise ValueError("News inference requires the configured Vertex backend")
        return cls(project=os.getenv("GCP_PROJECT", cls.project),
                   location=os.getenv("NEWS_AI_LOCATION", cls.location),
                   chat_model=os.getenv("NEWS_CHAT_MODEL", cls.chat_model),
                   embedding_model=os.getenv("NEWS_EMBEDDING_MODEL", cls.embedding_model))


class Vertex:
    def __init__(self, settings=None, credentials=None):
        self.settings = settings or VertexSettings.from_env()
        if credentials is None:
            credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"])
        self.client = genai.Client(
            vertexai=True, credentials=credentials, project=self.settings.project,
            location=self.settings.location,
            http_options=types.HttpOptions(api_version="v1", timeout=20000,
                                          retry_options=types.HttpRetryOptions(attempts=1)))

    def embed(self, text, *, document=False, title=None):
        response = self.client.models.embed_content(
            model=self.settings.embedding_model, contents=text,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT" if document else "RETRIEVAL_QUERY",
                title=title if document else None,
                output_dimensionality=self.settings.dimensions, auto_truncate=False))
        vectors = response.embeddings or []
        values = list(vectors[0].values or []) if len(vectors) == 1 else []
        if (len(values) != self.settings.dimensions
                or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in values)
                or not any(values)):
            raise ValueError("Embedding response has an invalid shape")
        return values

    def structured(self, instruction, payload, schema):
        response = self.client.models.generate_content(
            model=self.settings.chat_model, contents=json.dumps(payload, ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=instruction, response_mime_type="application/json",
                response_json_schema=schema, temperature=0, max_output_tokens=1800,
                thinking_config=types.ThinkingConfig(thinking_level="MINIMAL")))
        if not response.text:
            raise ValueError("No model response")
        return json.loads(response.text)

    def close(self):
        self.client.close()
