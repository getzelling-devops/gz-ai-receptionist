"""Update contact instructions and lead extraction without changing other assistant settings."""
import json
from pathlib import Path
import re
import subprocess
import httpx

instruction = Path("backend/contact-accuracy-prompt.md").read_text().strip()
properties = {
    "email": {"type":"string","description":"Exact most recently explicitly confirmed email address. Never invent local-part dots. Omit if not confirmed."},
    "email_confirmed": {"type":"boolean","description":"True only after explicit caller confirmation of the latest corrected email address; otherwise false."},
}
def update(config):
    prompt=config["model"]["messages"][0]["content"]
    if "## Contact accuracy" in prompt:
        prompt=re.sub(r"^## Contact accuracy\n.*?(?=^## |\Z)",instruction+"\n\n",prompt,flags=re.M|re.S)
    else:
        prompt=prompt.rstrip()+"\n\n"+instruction+"\n"
    config["model"]["messages"][0]["content"]=prompt
    plan=config.setdefault("analysisPlan",{}).setdefault("structuredDataPlan",{})
    plan["enabled"]=True
    schema=plan.setdefault("schema",{"type":"object","properties":{}})
    schema["properties"].update(properties)
    schema["properties"]["phone"]={"type":"string","description":"The confirmed caller callback, as NNN-NNN-NNNN for a ten-digit US number. Preserve international numbers and extensions."}
    return {"model":config["model"],"analysisPlan":config["analysisPlan"]}

phone=Path("backend/receptionist/phone_assistant.json")
data=json.loads(phone.read_text());update(data)
phone.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")
path=Path("backend/assistant-prompt.md")
text=path.read_text()
if "## Contact accuracy" not in text:path.write_text(text.rstrip()+"\n\n"+instruction+"\n")
key=subprocess.check_output(["gcloud","secrets","versions","access","latest","--project=gz-ai-receptionist","--secret=vapi-api-key"]).decode().strip()
with httpx.Client(base_url="https://api.vapi.ai",headers={"Authorization":"Bearer "+key},timeout=30) as client:
    for aid in ["8a1073de-713e-425d-8674-22e285e26d2e","83dbb599-ccda-4da2-a6ff-d17e9ce0cfd0"]:
        r=client.get("/assistant/"+aid);r.raise_for_status()
        config=r.json();payload=update(config)
        r=client.patch("/assistant/"+aid,json=payload);r.raise_for_status()
        print("Updated contact accuracy:",aid,r.json().get("latestVersion"))
