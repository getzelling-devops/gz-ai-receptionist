"""Prepare the signed lead tool; publish only after the backend revision is live."""
import argparse
import json
from pathlib import Path
import re
import subprocess

import httpx

ROOT = Path(__file__).resolve().parents[1]
PHONE = "83dbb599-ccda-4da2-a6ff-d17e9ce0cfd0"
WEB = "8a1073de-713e-425d-8674-22e285e26d2e"
ROLES = ["buyer", "seller", "investor", "other"]
parser = argparse.ArgumentParser()
parser.add_argument("--publish", action="store_true")
args = parser.parse_args()
key = subprocess.check_output(["gcloud", "secrets", "versions", "access", "latest",
    "--project=gz-ai-receptionist", "--secret=vapi-api-key"]).decode().strip()
instruction = (ROOT / "backend/lead-capture-prompt.md").read_text().strip()

def update(config, tid):
    model = config["model"]
    prompt = model["messages"][0]["content"]
    if "## Confirmed lead capture" in prompt:
        prompt = re.sub(r"^## Confirmed lead capture\n.*?(?=^## |\Z)", instruction + "\n\n", prompt, flags=re.M | re.S)
    else:
        prompt = prompt.rstrip() + "\n\n" + instruction + "\n"
    model["messages"][0]["content"] = prompt
    model["toolIds"] = list(dict.fromkeys([*model.get("toolIds", []), tid]))
    properties = config["analysisPlan"]["structuredDataPlan"]["schema"]["properties"]
    properties["lead_types"] = {"type": "array", "items": {"type": "string", "enum": ROLES},
        "description": "Explicitly stated interests. Other only if none established. May include multiple specific interests."}
    properties["lead_type"] = {"type": "string", "enum": ROLES, "description": "Primary explicitly stated interest."}
    return {"model": model, "analysisPlan": config["analysisPlan"]}

with httpx.Client(base_url="https://api.vapi.ai", headers={"Authorization": "Bearer " + key}, timeout=30) as client:
    def checked(response):
        if not response.is_success:
            raise RuntimeError(f"Vapi rejected configuration ({response.status_code})")
        return response.json()
    properties = {
        "name": {"type": "string", "description": "Name actually provided; never infer from email."},
        "email": {"type": "string", "description": "Exact confirmed email, retaining only explicitly stated punctuation."},
        "email_confirmed": {"type": "boolean", "description": "True only after explicit confirmation of this exact email."},
        "phone": {"type": "string", "description": "Complete confirmed callback. Ten-digit US numbers as NNN-NNN-NNNN."},
        "phone_confirmed": {"type": "boolean", "description": "True only after explicit confirmation of this callback."},
        "lead_types": {"type": "array", "items": {"type": "string", "enum": ROLES}},
        "summary": {"type": "string", "description": "Brief actual request and any requested follow-up; never promise delivery."},
    }
    url = "https://receptionist-staging-831469210783.us-east1.run.app/tools/capture-lead"
    tools = checked(client.get("/tool"))
    prior = next((t for t in tools if t.get("function", {}).get("name") == "capture-lead" and t.get("server", {}).get("url") == url), None)
    config = {"type": "function", "async": False, "function": {"name": "capture-lead",
        "description": "Save an explicitly confirmed follow-up inquiry for GetZelling. Required in web text as well as voice. Does not send a report or customer email.",
        "parameters": {"type": "object", "properties": properties, "required": ["lead_types", "summary"]}},
        "server": {"url": url, "timeoutSeconds": 40, "credentialId": "c963b19d-abd7-42d3-a583-0d94f82719b4"},
        "messages": [{"type": "request-start", "content": ""}]}
    tool = checked(client.patch("/tool/" + prior["id"], json=config) if prior else client.post("/tool", json=config))
    path = ROOT / "backend/receptionist/phone_assistant.json"
    phone = json.loads(path.read_text()); update(phone, tool["id"])
    path.write_text(json.dumps(phone, ensure_ascii=False, indent=2) + "\n")
    path = ROOT / "backend/assistant-prompt.md"
    text = path.read_text()
    if "## Confirmed lead capture" not in text:
        path.write_text(text.rstrip() + "\n\n" + instruction + "\n")
    print("Prepared signed capture tool:", tool["id"])
    if args.publish:
        for aid in (PHONE, WEB):
            config = checked(client.get("/assistant/" + aid))
            reply = checked(client.patch("/assistant/" + aid, json=update(config, tool["id"])))
            print("Published lead capture:", aid, reply.get("latestVersion"))
