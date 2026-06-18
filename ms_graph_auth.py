"""
PM Agent — Microsoft Graph OAuth (Delegated)
Handles one-time sign-in flow + token refresh for Mail.Send.

Token persistence:
  - Primary: TOKEN_DIR (set to a Railway volume like /data for persistence)
  - Bootstrap: MS_REFRESH_TOKEN env var (seed for first run after deploy)
  - Fallback: /tmp (wiped on deploy)

Endpoints:
  /auth/login    → redirects to Microsoft sign-in
  /auth/callback → receives auth code, stores refresh token
  /auth/status   → shows if authenticated
  /health        → health check for Railway
"""

import os
import json
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs
import requests

from config import MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET, log

REDIRECT_URI = os.environ.get(
    "MS_REDIRECT_URI",
    "https://alfred-production-d571.up.railway.app/auth/callback"
)
SCOPES = "https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/Mail.Read offline_access"

# Token storage: prefer persistent volume, fall back to /tmp
TOKEN_DIR = os.environ.get("TOKEN_DIR", "/tmp")
TOKEN_FILE = os.path.join(TOKEN_DIR, "ms_graph_token.json")

# Bootstrap: env var refresh token for surviving deploys without a volume
MS_REFRESH_TOKEN_ENV = os.environ.get("MS_REFRESH_TOKEN", "")

# In-memory token cache
_token_cache = {
    "access_token": None,
    "refresh_token": None,
    "expires_at": None,
}


def _save_tokens(data):
    """Save tokens to memory, disk, and Railway env var."""
    _token_cache["access_token"] = data.get("access_token")
    new_refresh = data.get("refresh_token", _token_cache.get("refresh_token"))
    old_refresh = _token_cache.get("refresh_token")
    _token_cache["refresh_token"] = new_refresh
    expires_in = data.get("expires_in", 3600)
    _token_cache["expires_at"] = (datetime.utcnow() + timedelta(seconds=expires_in - 60)).isoformat()

    try:
        os.makedirs(TOKEN_DIR, exist_ok=True)
        with open(TOKEN_FILE, "w") as f:
            json.dump(_token_cache, f)
        log.info(f"MS Graph: Tokens saved to {TOKEN_FILE}")
    except Exception as e:
        log.warning(f"MS Graph: Could not save tokens to disk: {e}")

    # Sync to Railway env var if the refresh token changed
    if new_refresh and new_refresh != old_refresh:
        try:
            from _railway_token_sync import sync_refresh_token
            sync_refresh_token(new_refresh)
        except Exception as e:
            log.debug(f"MS Graph: Railway sync skipped — {e}")


def _load_tokens():
    """Load tokens from disk, or bootstrap from env var."""
    if _token_cache.get("refresh_token"):
        return

    # Try loading from disk first
    try:
        with open(TOKEN_FILE, "r") as f:
            data = json.load(f)
            _token_cache.update(data)
            log.info(f"MS Graph: Tokens loaded from {TOKEN_FILE}")
            return
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning(f"MS Graph: Could not load tokens from disk: {e}")

    # Fall back to env var bootstrap
    if MS_REFRESH_TOKEN_ENV:
        _token_cache["refresh_token"] = MS_REFRESH_TOKEN_ENV
        log.info("MS Graph: Bootstrapped refresh token from MS_REFRESH_TOKEN env var")


def get_auth_url():
    """Build the Microsoft OAuth sign-in URL."""
    params = {
        "client_id": MS_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "response_mode": "query",
    }
    return f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/authorize?{urlencode(params)}"


def exchange_code(code):
    """Exchange authorization code for tokens."""
    resp = requests.post(
        f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token",
        data={
            "client_id": MS_CLIENT_ID,
            "client_secret": MS_CLIENT_SECRET,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
            "scope": SCOPES,
        },
        timeout=15,
    )
    if resp.status_code == 200:
        _save_tokens(resp.json())
        return True, None
    else:
        return False, f"Token exchange failed ({resp.status_code}): {resp.text[:300]}"


def refresh_access_token():
    """Refresh the access token using the stored refresh token."""
    _load_tokens()

    if not _token_cache.get("refresh_token"):
        return None, "No refresh token — visit /auth/login to authenticate"

    # Check if current token is still valid
    if _token_cache.get("access_token") and _token_cache.get("expires_at"):
        if datetime.utcnow().isoformat() < _token_cache["expires_at"]:
            return _token_cache["access_token"], None

    log.info("MS Graph: Refreshing access token...")
    resp = requests.post(
        f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token",
        data={
            "client_id": MS_CLIENT_ID,
            "client_secret": MS_CLIENT_SECRET,
            "refresh_token": _token_cache["refresh_token"],
            "grant_type": "refresh_token",
            "scope": SCOPES,
        },
        timeout=15,
    )
    if resp.status_code == 200:
        _save_tokens(resp.json())
        return _token_cache["access_token"], None
    else:
        return None, f"Token refresh failed ({resp.status_code}): {resp.text[:300]}"


def is_authenticated():
    """Check if we have a valid refresh token."""
    _load_tokens()
    return bool(_token_cache.get("refresh_token"))


# ══════════════════════════════════════════════════════════════════════════════
# HTTP SERVER
# ══════════════════════════════════════════════════════════════════════════════

class AuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/auth/login":
            url = get_auth_url()
            self.send_response(302)
            self.send_header("Location", url)
            self.end_headers()

        elif path == "/auth/callback":
            params = parse_qs(parsed.query)
            code = params.get("code", [None])[0]
            error = params.get("error", [None])[0]

            if error:
                self._respond(400, f"Auth error: {error} — {params.get('error_description', [''])[0]}")
                return

            if not code:
                self._respond(400, "No authorization code received.")
                return

            ok, err = exchange_code(code)
            if ok:
                rt = _token_cache.get("refresh_token", "")
                rt_display = rt[:20] + "..." if len(rt) > 20 else rt
                self._respond(200,
                    "✅ Authenticated! PM Agent can now send emails as axel@axiscrm.com.au.<br><br>"
                    "<b>To survive deploys:</b> copy the token below and set it as <code>MS_REFRESH_TOKEN</code> "
                    "in Railway environment variables.<br><br>"
                    f"<textarea rows='3' cols='60' onclick='this.select()' style='font-size:11px;'>{rt}</textarea><br><br>"
                    "<small>Or add a Railway volume at <code>/data</code> and set <code>TOKEN_DIR=/data</code></small>"
                )
                log.info(f"MS Graph: OAuth flow complete — refresh token starts with {rt_display}")
            else:
                self._respond(500, f"❌ Token exchange failed: {err}")

        elif path == "/auth/status":
            if is_authenticated():
                self._respond(200, "✅ Authenticated — refresh token present.")
            else:
                login_url = get_auth_url()
                self._respond(200, f'❌ Not authenticated. <a href="{login_url}">Click here to sign in</a>')

        elif path == "/health":
            self._respond(200, "ok")

        else:
            self._respond(404, "Not found")

    def _respond(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        html = f"""<!DOCTYPE html><html><head><title>PM Agent</title>
        <style>body{{font-family:system-ui;max-width:600px;margin:80px auto;padding:20px;text-align:center}}</style>
        </head><body><h2>{body}</h2></body></html>"""
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass  # Suppress default HTTP logs


def start_auth_server(port=8080):
    """Start the OAuth callback server in a daemon thread."""
    _load_tokens()
    server = HTTPServer(("0.0.0.0", port), AuthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info(f"Auth server started on port {port}")
    return server
