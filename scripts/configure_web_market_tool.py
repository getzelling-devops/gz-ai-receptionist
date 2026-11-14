"""Attach shared Market insights retrieval to the website staging assistant only."""
import argparse
import json
import subprocess
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--backend-url", required=True)
args = parser.parse_args()
aid = "8a1073de-713e-425d-8674-22e285e26d2e"
key = subprocess.check_output(["gcloud", "secrets", "versions", "access", "latest",
    "--project=gz-ai-receptionist", "--secret=vapi-api-key"]).decode().strip()
with httpx.Client(base_url="https://api.vapi.ai", headers={"Authorization": "Bearer " + key}, timeout=30) as client:
    def checked(response):
        if not response.is_success:
            raise RuntimeError(f"Vapi configuration rejected ({response.status_code}): {response.text[:350]}")
        return response.json()

    assistant = checked(client.get("/assistant/" + aid))
    existing = checked(client.get("/tool"))
    tool = next((t for t in existing if t.get("function", {}).get("name") == "market-insights"
                 and t.get("server", {}).get("url") == args.backend_url + "/tools/market-insights"), None)
    config = {
        "type": "function", "async": False,
        "function": {"name": "market-insights", "description":
            "Search GetZelling's dated Market insights collection. Required before giving market facts in text or voice. "
            "Include the visitor's location, topic, desired period and latest language in question. "
            "For current conditions preserve the visitor's request for today so the service can identify outdated evidence.",
            "parameters": {"type": "object", "properties": {"question": {"type": "string",
                "description": "A standalone market question in the visitor's language, with context and requested dates."}},
                "required": ["question"]}},
        "server": {"url": args.backend_url + "/tools/market-insights", "timeoutSeconds": 65,
                   "credentialId": "c963b19d-abd7-42d3-a583-0d94f82719b4"},
        "messages": [{"type": "request-start", "content": ""}],
    }
    reply = checked(client.patch("/tool/" + tool["id"], json=config) if tool
                    else client.post("/tool", json=config))
    model = assistant["model"]
    prompt = model["messages"][0]["content"]
    start = prompt.index("## Market questions")
    end = prompt.index("\n## ", start + 3)
    market = Path("backend/website-market-prompt.md").read_text()

    prompt = prompt[:start] + market + prompt[end:]
    model["messages"][0]["content"] = prompt
    model["toolIds"] = list(dict.fromkeys([*model["toolIds"], reply["id"]]))
    updated = checked(client.patch("/assistant/" + aid, json={"model": model}))
    print(json.dumps({"assistant_id": aid, "version": updated.get("latestVersion"), "tool_id": reply["id"],
                      "backend_url": args.backend_url}, indent=2))
