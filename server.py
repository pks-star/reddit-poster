#!/usr/bin/env python3
"""Landing Clinic outreach poster — local-only backend.

Runs on the user's own machine (localhost). Handles Reddit OAuth (web-app flow)
and posts comments via the Reddit API using the USER'S OWN Reddit account.

Security model:
- Reddit tokens live in config.json (0600) next to this file. They never leave
  this machine except to reddit's official OAuth endpoints.
- The browser (admin console) only ever talks to localhost.
- The user pastes their OWN Reddit app client_id/secret into config.json
  themselves. This tool never asks for them in chat and never transmits them
  anywhere except https://www.reddit.com and https://oauth.reddit.com.

Setup:
    cp config.example.json config.json   # then fill in your Reddit app credentials
    ./start_poster.sh                    # or: python3 server.py

Then open the admin console -> Outreach tab -> Connect Reddit.
"""
import base64
import json
import os
import re
import secrets
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

AUTH_URL = "https://www.reddit.com/api/v1/authorize"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"
SCOPES = "identity,submit"

# in-memory OAuth state tokens -> created_at
_states = {}


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(CONFIG_PATH, 0o600)


def ua(cfg):
    return cfg.get("user_agent", "linux:landingclinic-poster:1.0")


def _http(method, url, data=None, headers=None):
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def reddit_token_request(cfg, data):
    creds = "%s:%s" % (cfg["reddit_client_id"], cfg["reddit_client_secret"])
    basic = base64.b64encode(creds.encode()).decode()
    return _http("POST", TOKEN_URL, data, {
        "Authorization": "Basic " + basic,
        "User-Agent": ua(cfg),
        "Content-Type": "application/x-www-form-urlencoded",
    })


def ensure_access_token(cfg):
    """Return (access_token, error). Refreshes when expired."""
    tok = cfg.get("reddit_access_token")
    exp = cfg.get("reddit_access_expires_at", 0)
    if tok and exp > time.time() + 60:
        return tok, None
    refresh = cfg.get("reddit_refresh_token")
    if not refresh:
        return None, "Reddit not connected — click Connect Reddit in the admin console."
    status, body = reddit_token_request(cfg, {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
    })
    try:
        j = json.loads(body)
    except Exception:
        return None, "Token refresh failed (HTTP %s)." % status
    if status != 200 or "access_token" not in j:
        return None, "Token refresh failed: %s" % j.get("error", "HTTP %s" % status)
    cfg["reddit_access_token"] = j["access_token"]
    cfg["reddit_access_expires_at"] = time.time() + int(j.get("expires_in", 3600)) - 60
    save_config(cfg)
    return cfg["reddit_access_token"], None


def reddit_me(cfg, token):
    status, body = _http("GET", API_BASE + "/api/v1/me", None, {
        "Authorization": "Bearer " + token,
        "User-Agent": ua(cfg),
    })
    if status != 200:
        return None
    try:
        return json.loads(body).get("name")
    except Exception:
        return None


def post_comment(cfg, thread_url, text):
    m = re.search(r"/comments/([A-Za-z0-9]+)", thread_url or "")
    if not m:
        return {"ok": False, "error": "Could not parse thread ID from URL."}
    thing_id = "t3_" + m.group(1)
    if not text or not text.strip():
        return {"ok": False, "error": "Empty reply text."}
    if len(text) > 9000:
        return {"ok": False, "error": "Reply too long for a Reddit comment."}
    token, err = ensure_access_token(cfg)
    if err:
        return {"ok": False, "error": err}
    status, body = _http("POST", API_BASE + "/api/comment", {
        "thing_id": thing_id,
        "text": text,
        "api_type": "json",
    }, {
        "Authorization": "Bearer " + token,
        "User-Agent": ua(cfg),
        "Content-Type": "application/x-www-form-urlencoded",
    })
    try:
        j = json.loads(body)
    except Exception:
        return {"ok": False, "error": "Reddit returned HTTP %s." % status}
    errors = (j.get("json") or {}).get("errors") or []
    if errors:
        # errors look like ["RATELIMIT", "you are doing that too much...", "field"]
        return {"ok": False, "error": "Reddit rejected it: %s" % "; ".join(e[1] or e[0] for e in errors)}
    try:
        thing = j["json"]["data"]["things"][0]["data"]
        return {"ok": True, "comment_id": thing.get("name"), "permalink": thing.get("permalink", "")}
    except Exception:
        return {"ok": False, "error": "Unexpected Reddit response."}


class Handler(BaseHTTPRequestHandler):
    server_version = "LandingClinicPoster/1.0"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _html(self, title, body, code=200):
        page = ("<!doctype html><html><head><meta charset=utf-8><title>%s</title>"
                "<style>body{font-family:system-ui,sans-serif;max-width:560px;margin:60px auto;padding:0 20px}"
                ".ok{color:#0a7a3d}.err{color:#b00020}</style></head>"
                "<body><h1>%s</h1>%s</body></html>") % (title, title, body)
        data = page.encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/api/status":
            try:
                cfg = load_config()
            except Exception:
                return self._json({"ok": True, "running": True, "reddit_connected": False,
                                   "error": "config.json missing — copy config.example.json first."})
            connected = bool(cfg.get("reddit_refresh_token"))
            user = cfg.get("reddit_user") if connected else None
            if connected and not user:
                token, _ = ensure_access_token(cfg)
                if token:
                    user = reddit_me(cfg, token)
                    if user:
                        cfg["reddit_user"] = user
                        save_config(cfg)
            return self._json({"ok": True, "running": True,
                               "reddit_connected": connected, "reddit_user": user})

        if path == "/api/auth/reddit":
            try:
                cfg = load_config()
            except Exception:
                return self._html("Not configured",
                    "<p class=err>config.json not found. Copy config.example.json to config.json "
                    "and fill in your Reddit app credentials first.</p>", 500)
            if not cfg.get("reddit_client_id") or "PASTE_" in str(cfg.get("reddit_client_id", "")):
                return self._html("Not configured",
                    "<p class=err>reddit_client_id is not set in config.json. "
                    "Create an app at reddit.com/prefs/apps (type: web app, redirect URI: "
                    + cfg.get("redirect_uri", "") + ") and paste the credentials.</p>", 500)
            state = secrets.token_urlsafe(24)
            _states[state] = time.time()
            params = urllib.parse.urlencode({
                "client_id": cfg["reddit_client_id"],
                "response_type": "code",
                "state": state,
                "redirect_uri": cfg.get("redirect_uri"),
                "duration": "permanent",
                "scope": SCOPES,
            })
            self.send_response(302)
            self.send_header("Location", AUTH_URL + "?" + params)
            self.end_headers()
            return

        if path == "/callback":
            code = (qs.get("code") or [None])[0]
            state = (qs.get("state") or [None])[0]
            err = (qs.get("error") or [None])[0]
            if err:
                return self._html("Authorization declined",
                    "<p class=err>Reddit returned: %s. Close this tab and try again.</p>" % err, 400)
            if not code or state not in _states or time.time() - _states.pop(state, 0) > 600:
                return self._html("Bad request",
                    "<p class=err>Missing or expired state. Start again from the admin console.</p>", 400)
            cfg = load_config()
            status, body = reddit_token_request(cfg, {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": cfg.get("redirect_uri"),
            })
            try:
                j = json.loads(body)
            except Exception:
                j = {}
            if status != 200 or "access_token" not in j:
                return self._html("Token exchange failed",
                    "<p class=err>%s. Check your client_id/secret and redirect URI match the "
                    "Reddit app settings exactly.</p>" % (j.get("error", "HTTP %s" % status)), 500)
            cfg["reddit_access_token"] = j["access_token"]
            cfg["reddit_access_expires_at"] = time.time() + int(j.get("expires_in", 3600)) - 60
            if j.get("refresh_token"):
                cfg["reddit_refresh_token"] = j["refresh_token"]
            user = reddit_me(cfg, cfg["reddit_access_token"])
            if user:
                cfg["reddit_user"] = user
            save_config(cfg)
            return self._html("Connected",
                "<p class=ok><b>Reddit connected%s.</b></p>"
                "<p>You can close this tab and go back to the admin console — "
                "the Post buttons are now live.</p>" % (" as /u/" + user if user else ""))

        return self._html("Landing Clinic poster",
            "<p>Local outreach posting backend is running.</p>"
            "<p>Open the admin console &rarr; Outreach tab to connect Reddit and post.</p>")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            payload = {}

        if parsed.path == "/api/disconnect":
            try:
                cfg = load_config()
                for k in ("reddit_access_token", "reddit_refresh_token",
                          "reddit_access_expires_at", "reddit_user"):
                    cfg.pop(k, None)
                save_config(cfg)
            except Exception:
                pass
            return self._json({"ok": True})

        if parsed.path == "/api/post":
            try:
                cfg = load_config()
            except Exception:
                return self._json({"ok": False, "error": "config.json missing."})
            result = post_comment(cfg, payload.get("thread_url"), payload.get("text"))
            return self._json(result)

        return self._json({"ok": False, "error": "Unknown endpoint."}, 404)

    def log_message(self, fmt, *args):  # quieter logs
        print("[poster] " + fmt % args)


def main():
    try:
        cfg = load_config()
    except Exception:
        cfg = {}
    port = int(cfg.get("port", 8099))
    if not os.path.exists(CONFIG_PATH):
        print("[poster] WARNING: config.json not found — copy config.example.json first.")
    else:
        os.chmod(CONFIG_PATH, 0o600)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("[poster] Listening on http://localhost:%d (localhost only)" % port)
    srv.serve_forever()


if __name__ == "__main__":
    main()
