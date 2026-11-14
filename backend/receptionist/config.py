"""Only secret names and routing settings come from the environment."""
import json
import os
import threading
from functools import lru_cache
from time import monotonic

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud import secretmanager

PROJECT = os.getenv("GCP_PROJECT", "gz-ai-receptionist")


@lru_cache
def secret_client():
    # Application Default Credentials: Cloud Run service identity or local ADC.
    return secretmanager.SecretManagerServiceClient()


_secret_cache = {}
_secret_lock = threading.Lock()


def secret(setting, default):
    name = os.getenv(setting, default)
    with _secret_lock:
        cached = _secret_cache.get(name)
        if cached and cached[0] > monotonic():
            return cached[1]
        resource = f"projects/{PROJECT}/secrets/{name}/versions/latest"
        value = secret_client().access_secret_version(name=resource, timeout=5).payload.data
        if not value:
            raise RuntimeError(f"Empty secret: {name}")
        _secret_cache[name] = (monotonic() + 60, value)
        return value


_db_lock = threading.Lock()


@lru_cache
def database():
    with _db_lock:
        try:
            app = firebase_admin.get_app("receptionist")
        except ValueError:
            mode = os.getenv("FIREBASE_AUTH_MODE", "secret")
            if mode == "runtime":
                credential = credentials.ApplicationDefault()
            elif mode == "secret":
                account = json.loads(secret("FIREBASE_ACCOUNT_SECRET", "firebase-service-account"))
                credential = credentials.Certificate(account)
            else:
                raise ValueError("Unknown FIREBASE_AUTH_MODE")
            app = firebase_admin.initialize_app(credential, {"projectId": PROJECT}, name="receptionist")
    return firestore.client(app, database_id=os.getenv("FIRESTORE_DATABASE", "(default)"))
