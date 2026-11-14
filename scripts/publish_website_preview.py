"""Clone the live website into an expiring Gizelle preview with an embedded launcher."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--widget-origin", required=True)
parser.add_argument("--receipt", type=Path, required=True)
args = parser.parse_args()
origin = args.widget_origin.rstrip("/")
if not re.fullmatch(r"https://[a-z0-9.-]+", origin):
    raise ValueError("Expected a fixed HTTPS widget origin")
site = "gz-gz-website"
channel = "gizelle-pilot"
api = "https://firebasehosting.googleapis.com/v1beta1/"
token = subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode().strip()
headers = {"Authorization": "Bearer " + token, "X-Goog-User-Project": site}
with httpx.Client(headers=headers, timeout=60) as client:
    def request(method, path, **kw):
        response = client.request(method, api + path, **kw)
        response.raise_for_status()
        return response.json()

    live = request("GET", f"sites/{site}/channels/live")
    source = live["release"]["version"]["name"]
    response = client.get(api + f"sites/{site}/channels/{channel}")
    if response.status_code == 404:
        target = request("POST", f"sites/{site}/channels", params={"channelId": channel},
                         json={"ttl": "604800s"})
    else:
        response.raise_for_status()
        target = response.json()
    operation = request("POST", f"sites/{site}/versions:clone",
                        json={"sourceVersion": source, "finalize": False})
    while not operation.get("done"):
        time.sleep(2)
        operation = request("GET", operation["name"])
    if operation.get("error"):
        raise RuntimeError(str(operation["error"]))
    version = operation["response"]["name"]
    source_files = []
    page_token = None
    while True:
        result = request("GET", source + "/files",
                         params={"pageSize": 1000, **({"pageToken": page_token} if page_token else {})})
        source_files.extend(result.get("files", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    payloads = {"/gizelle-widget.js": Path("website/gizelle-widget.js").read_bytes()}
    injection = f'<script defer src="/gizelle-widget.js" data-widget-origin="{origin}"></script>'
    # A standalone test page contains no access-controlled website content.
    payloads["/gizelle-preview.html"] = Path("website/gizelle-preview.html").read_text().replace(
        "</body>", injection + "</body>").encode()
    html_paths = [f["path"] for f in source_files if f["path"].endswith(".html")]

    def amended(path):
        response = httpx.get("https://" + site + ".web.app" + path, follow_redirects=True, timeout=30)
        response.raise_for_status()
        text = response.text
        if not re.search(r"<html\b", text, re.I):
            return None
        text = re.sub(r"</body>", injection + "\n</body>", text, count=1, flags=re.I)
        return path, text.encode()

    with ThreadPoolExecutor(max_workers=6) as pool:
        for item in pool.map(amended, html_paths):
            if item:
                payloads[item[0]] = item[1]
    compressed = {path: gzip.compress(body, mtime=0) for path, body in payloads.items()}
    hashes = {path: hashlib.sha256(body).hexdigest() for path, body in compressed.items()}
    needed = request("POST", version + ":populateFiles", json={"files": hashes})
    by_hash = {hashes[path]: body for path, body in compressed.items()}
    for digest in needed.get("uploadRequiredHashes", []):
        response = client.post(needed["uploadUrl"] + "/" + digest, content=by_hash[digest],
                               headers={"Content-Type": "application/octet-stream"})
        response.raise_for_status()
    config = live["release"]["version"].get("config", {})
    config.setdefault("headers", []).append({"glob": "**", "headers": {
        "Permissions-Policy": f'microphone=(self "{origin}" "https://gizelle.getzelling.com")'
    }})
    request("PATCH", version, params={"updateMask": "config,status"},
            json={"status": "FINALIZED", "config": config})
    release = request("POST", f"sites/{site}/channels/{channel}/releases",
                       params={"versionName": version}, json={"message": "Gizelle hosted private preview"})
    after = request("GET", f"sites/{site}/channels/live")
    if after["release"]["version"]["name"] != source:
        raise RuntimeError("Live release changed during preview deployment; inspect before retrying")
    receipt = {"channel": channel, "url": target["url"], "version": version,
               "source_live_version": source, "amended_pages": len(payloads) - 1,
               "widget_origin": origin, "release": release["name"]}
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
