"""Google Photos Picker flow: open the picker, wait for your selection, download it.

    python photos_picker.py                 # pick, download to data/picked/<session>
    python photos_picker.py --reel          # ...then build a reel from the picks
    python photos_picker.py --max 10        # cap how many items can be picked

One-time setup: in Google Cloud Console enable the "Photos Picker API", create an
OAuth client of type "Desktop app", download its JSON to
data/google_client_secret.json (or set GOOGLE_CLIENT_SECRET). The first run opens
a Google sign-in; the refresh token is kept in data/google_token.json.

Uses only the standard library: OAuth loopback flow with PKCE, then the Picker REST API.
"""
import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
CLIENT_SECRET = Path(os.getenv("GOOGLE_CLIENT_SECRET", DATA / "google_client_secret.json"))
TOKEN_PATH = DATA / "google_token.json"
PICKED_DIR = DATA / "picked"

SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"
API = "https://photospicker.googleapis.com/v1"


# ---------- OAuth ----------

def _post_form(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data)) as resp:
        return json.load(resp)


def _client_config() -> dict:
    if not CLIENT_SECRET.exists():
        sys.exit(f"Missing {CLIENT_SECRET}. See setup notes at the top of photos_picker.py.")
    cfg = json.loads(CLIENT_SECRET.read_text())
    return cfg.get("installed") or cfg.get("web") or cfg


def _authorize(cfg: dict) -> dict:
    """Run the browser sign-in once and return the token response."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if "code" in query or "error" in query:
                result.update(query)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h3>SHA-I is connected to Google Photos. You can close this tab.</h3>")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_port}/"
    url = cfg.get("auth_uri", "https://accounts.google.com/o/oauth2/auth") + "?" + urllib.parse.urlencode({
        "client_id": cfg["client_id"], "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPE, "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent",
    })
    print("Opening Google sign-in in your browser...")
    webbrowser.open(url)
    while "code" not in result and "error" not in result:
        server.handle_request()
    server.server_close()
    if result.get("state") != state or "error" in result:
        sys.exit(f"Google sign-in failed: {result.get('error', 'state mismatch')}")
    return _post_form(cfg.get("token_uri", "https://oauth2.googleapis.com/token"), {
        "code": result["code"], "client_id": cfg["client_id"], "client_secret": cfg.get("client_secret", ""),
        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier,
    })


def access_token() -> str:
    cfg = _client_config()
    token = json.loads(TOKEN_PATH.read_text()) if TOKEN_PATH.exists() else {}
    if token.get("access_token") and token.get("expires_at", 0) > time.time() + 60:
        return token["access_token"]
    if token.get("refresh_token"):
        fresh = _post_form(cfg.get("token_uri", "https://oauth2.googleapis.com/token"), {
            "refresh_token": token["refresh_token"], "client_id": cfg["client_id"],
            "client_secret": cfg.get("client_secret", ""), "grant_type": "refresh_token",
        })
        fresh.setdefault("refresh_token", token["refresh_token"])
    else:
        fresh = _authorize(cfg)
    fresh["expires_at"] = time.time() + int(fresh.get("expires_in", 3600))
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(fresh))
    return fresh["access_token"]


# ---------- Picker API ----------

def api(method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    req = urllib.request.Request(
        f"{API}/{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token or access_token()}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"Picker API {method} {path} failed ({e.code}): {e.read().decode()[:300]}")
    return json.loads(raw) if raw else {}


def _seconds(duration: str, default: float) -> float:
    try:
        return float(duration.rstrip("s"))
    except (AttributeError, ValueError):
        return default


def create_session(max_items: int | None = None) -> dict:
    body = {"pickingConfig": {"maxItemCount": str(max_items)}} if max_items else {}
    return api("POST", "sessions", body)


def wait_for_selection(session: dict) -> None:
    polling = session.get("pollingConfig", {})
    interval = _seconds(polling.get("pollInterval"), 5)
    deadline = time.time() + _seconds(polling.get("timeoutIn"), 1800)
    print("Waiting for you to finish picking in Google Photos", end="", flush=True)
    while time.time() < deadline:
        if api("GET", f"sessions/{session['id']}").get("mediaItemsSet"):
            print(" done.")
            return
        print(".", end="", flush=True)
        time.sleep(interval)
    sys.exit("\nPicker session timed out before anything was picked.")


def list_items(session_id: str) -> list[dict]:
    items, page = [], None
    while True:
        query = {"sessionId": session_id, "pageSize": 100, **({"pageToken": page} if page else {})}
        resp = api("GET", "mediaItems?" + urllib.parse.urlencode(query))
        items += resp.get("mediaItems", [])
        page = resp.get("nextPageToken")
        if not page:
            return items


def download(item: dict, folder: Path, token: str) -> Path:
    media = item["mediaFile"]
    suffix = "=dv" if item.get("type") == "VIDEO" else "=d"  # original video / full-res photo
    name = media.get("filename") or f"{item['id']}.bin"
    dest = folder / name
    req = urllib.request.Request(media["baseUrl"] + suffix, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    return dest


def pick(max_items: int | None = None) -> Path:
    """Run the full flow and return the folder holding the downloaded picks."""
    session = create_session(max_items)
    uri = session["pickerUri"]
    print(f"Pick your clips here (opening in browser): {uri}")
    webbrowser.open(uri)
    try:
        wait_for_selection(session)
        items = list_items(session["id"])
        folder = PICKED_DIR / session["id"]
        folder.mkdir(parents=True, exist_ok=True)
        token = access_token()
        for i, item in enumerate(items, 1):
            path = download(item, folder, token)
            print(f"  [{i}/{len(items)}] {path.name}")
        return folder
    finally:
        api("DELETE", f"sessions/{session['id']}")  # Google asks clients to clean up sessions


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max", type=int, help="max items the picker allows")
    parser.add_argument("--reel", action="store_true", help="build a reel from the picks")
    parser.add_argument("--hook", help="topic for a Nemotron-written caption on the reel")
    args = parser.parse_args()
    folder = pick(args.max)
    print(f"Saved picks to {folder}")
    if args.reel:
        import reel
        print(f"Reel saved to {reel.build(reel.media_in(folder), hook=args.hook)}")
