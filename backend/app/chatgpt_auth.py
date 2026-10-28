"""Sign in with ChatGPT (ChatGPT plan usage for local/open-source apps).

Implements the documented flow for locally hosted apps:
  - dynamic client registration through the authorization request (client_id=dynamic_agent_client)
  - OAuth 2.0 authorization code + PKCE with a loopback redirect on 127.0.0.1
  - token exchange / rotating refresh tokens / revocation
Credentials are stored only in data/chatgpt_auth.json.
Docs: https://developers.openai.com/siwc/token-sharing-open-source
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timezone

import httpx

from .config import DATA_DIR, load_settings, save_settings

AUTH_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
OIDC_CONFIG_URL = "https://auth.openai.com/.well-known/openid-configuration"
ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
AGENT_NAME = "Paper Reader"
CALLBACK_PATH = "/auth/callback"

HOST_FILE = DATA_DIR / "chatgpt_host.json"
CRED_FILE = DATA_DIR / "chatgpt_auth.json"

_lock = threading.RLock()
_pending: dict | None = None          # in-progress login attempt
_oidc_cache: dict | None = None


class AuthError(Exception):
    pass


# ---------------------------------------------------------------- storage
def _host_id() -> str:
    if HOST_FILE.exists():
        try:
            hid = json.loads(HOST_FILE.read_text("utf-8")).get("ext_agent_host_id")
            if hid:
                return hid
        except Exception:
            pass
    hid = f"urn:uuid:{uuid.uuid4()}"
    HOST_FILE.write_text(json.dumps({"ext_agent_host_id": hid}), "utf-8")
    return hid


def load_credentials() -> dict | None:
    if not CRED_FILE.exists():
        return None
    try:
        return json.loads(CRED_FILE.read_text("utf-8"))
    except Exception:
        return None


def _save_credentials(c: dict | None) -> None:
    with _lock:
        if c is None:
            if CRED_FILE.exists():
                CRED_FILE.unlink()
            return
        tmp = CRED_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(c, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(CRED_FILE)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _jwt_payload_unverified(token: str) -> dict:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


def _oidc_config() -> dict:
    global _oidc_cache
    if _oidc_cache is None:
        r = httpx.get(OIDC_CONFIG_URL, timeout=15)
        r.raise_for_status()
        _oidc_cache = r.json()
    return _oidc_cache


def _verify_id_token(id_token: str, client_id: str, nonce: str) -> dict:
    """Validate signature/issuer/audience/expiry/nonce. Falls back to claim checks if PyJWT is missing."""
    try:
        import jwt  # PyJWT
        from jwt import PyJWKClient

        jwks_uri = _oidc_config().get("jwks_uri")
        key = PyJWKClient(jwks_uri).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(id_token, key.key, algorithms=["RS256", "ES256"], audience=client_id, issuer=ISSUER)
    except ImportError:
        claims = _jwt_payload_unverified(id_token)
        if claims.get("iss") != ISSUER or client_id not in str(claims.get("aud")):
            raise AuthError("ID 토큰의 발급자/대상이 일치하지 않습니다.")
        if claims.get("exp", 0) < time.time():
            raise AuthError("ID 토큰이 만료되었습니다.")
    if claims.get("nonce") != nonce:
        raise AuthError("ID 토큰 nonce가 일치하지 않습니다.")
    return claims


# ---------------------------------------------------------------- status
def status() -> dict:
    c = load_credentials()
    if not c:
        return {"logged_in": False, "pending": bool(_pending and _pending.get("result") is None)}
    scopes = c.get("scopes") or []
    return {
        "logged_in": True,
        "email": c.get("email", ""),
        "sharing": PLAN_SCOPE in scopes,
        "scopes": scopes,
        "expires_at": c.get("saved_at_ts", 0) + int(c.get("expires_in", 3600)),
        "client_id": c.get("client_id", ""),
        "pending": bool(_pending and _pending.get("result") is None),
        "last_error": (_pending or {}).get("result") if _pending and _pending.get("result") not in (None, "ok") else "",
    }


# ---------------------------------------------------------------- login flow
class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def _reply(self, code: int, title: str, body: str):
        html = (f"<!doctype html><html lang='ko'><meta charset='utf-8'><title>{title}</title>"
                f"<body style='font-family:sans-serif;padding:40px'><h2>{title}</h2><p>{body}</p></body></html>")
        data = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        global _pending
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self._reply(404, "Not found", "")
            return
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        p = _pending
        try:
            if not p or q.get("state") != p["state"]:
                raise AuthError("state 값이 일치하지 않습니다. 설정 화면에서 로그인을 다시 시작하세요.")
            if q.get("error"):
                raise AuthError(f"로그인이 취소되었습니다 ({q.get('error')}).")
            code = q.get("code")
            if not code:
                raise AuthError("콜백에 code가 없습니다.")
            issued = q.get("client_id") or p["client_id"]
            if p["client_id"] != "dynamic_agent_client" and q.get("client_id") and q["client_id"] != p["client_id"]:
                raise AuthError("콜백의 client_id가 저장된 값과 다릅니다.")
            if issued == "dynamic_agent_client":
                raise AuthError("등록이 완료되지 않았습니다 (issued client_id 없음). 다시 시도하세요.")
            _exchange_code(p, code, issued)
            p["result"] = "ok"
            self._reply(200, "로그인 완료", "Paper Reader에 ChatGPT 계정이 연결되었습니다. 이 창을 닫고 앱으로 돌아가세요.")
        except Exception as e:  # noqa: BLE001
            if p is not None:
                p["result"] = str(e)
            self._reply(400, "로그인 실패", str(e))
        finally:
            threading.Thread(target=self.server.shutdown, daemon=True).start()


def _exchange_code(p: dict, code: str, client_id: str) -> None:
    r = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": p["verifier"],
            "redirect_uri": p["redirect_uri"],
            "resource": RESOURCE,
        },
        timeout=30,
    )
    if r.status_code != 200:
        raise AuthError(f"토큰 교환 실패 ({r.status_code}): {r.text[:300]}")
    tok = r.json()
    claims = _verify_id_token(tok.get("id_token", ""), client_id, p["nonce"]) if tok.get("id_token") else {}
    scopes = (tok.get("scope") or "").split()
    cred = {
        "email": claims.get("email", ""),
        "issuer": ISSUER,
        "subject": claims.get("sub", ""),
        "client_id": client_id,
        "ext_agent_host_id": p["host_id"],
        "id_token": tok.get("id_token", ""),
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token", ""),
        "token_type": tok.get("token_type", "Bearer"),
        "expires_in": int(tok.get("expires_in", 3600)),
        "scopes": scopes,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "saved_at_ts": time.time(),
    }
    _save_credentials(cred)
    _after_login(cred)


def _after_login(cred: dict) -> None:
    """Pick a default model and make ChatGPT the default provider if nothing else is configured."""
    s = load_settings()
    cfg = s["providers"].setdefault("chatgpt", {"api_key": "", "model": "", "base_url": ""})
    if not cfg.get("model"):
        try:
            models = list_models_sync(cred["access_token"])
            if models:
                cfg["model"] = models[0]["slug"]
        except Exception:
            pass
    from .config import api_key_for
    if not any(api_key_for(n, s) for n in ("anthropic", "openai", "gemini", "deepseek")):
        s["default_provider"] = "chatgpt"
    save_settings(s)


def start_login() -> dict:
    """Start the loopback listener and return the authorization URL to open in a browser."""
    global _pending
    with _lock:
        if _pending and _pending.get("result") is None and _pending.get("server"):
            try:
                _pending["server"].shutdown()
            except Exception:
                pass
        existing = load_credentials() or {}
        client_id = existing.get("client_id") or "dynamic_agent_client"
        verifier = _b64url(secrets.token_bytes(48))
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
        state = _b64url(secrets.token_bytes(24))
        nonce = _b64url(secrets.token_bytes(24))

        # The redirect URI is always http://127.0.0.1:<port>/auth/callback (OpenAI requires the loopback
        # address). In Docker, set PAPER_READER_OAUTH_PORT to a published port and PAPER_READER_OAUTH_BIND=0.0.0.0
        # so the browser on the host can reach the listener inside the container.
        bind = os.environ.get("PAPER_READER_OAUTH_BIND", "127.0.0.1")
        try:
            want_port = int(os.environ.get("PAPER_READER_OAUTH_PORT", "0"))
        except ValueError:
            want_port = 0
        try:
            srv = http.server.HTTPServer((bind, want_port), _CallbackHandler)
        except OSError as e:
            raise AuthError(f"로그인 콜백 포트({want_port})를 열 수 없습니다: {e}")
        port = srv.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}{CALLBACK_PATH}"
        params = {
            "client_id": client_id,
            "ext_agent_host_id": _host_id(),
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "resource": RESOURCE,
            "state": state,
            "nonce": nonce,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        if client_id == "dynamic_agent_client":
            params["agent_name_hint"] = AGENT_NAME
        else:
            if existing.get("id_token"):
                params["id_token_hint"] = existing["id_token"]
            if existing.get("email"):
                params["login_hint"] = existing["email"]
        url = AUTH_URL + "?" + urllib.parse.urlencode(params)
        _pending = {
            "state": state, "nonce": nonce, "verifier": verifier, "redirect_uri": redirect_uri,
            "client_id": client_id, "host_id": params["ext_agent_host_id"], "server": srv, "result": None,
            "started": time.time(),
        }
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        # give up after 10 minutes (daemon timer so it never blocks interpreter shutdown)
        timer = threading.Timer(600, srv.shutdown)
        timer.daemon = True
        timer.start()
        return {"url": url, "redirect_uri": redirect_uri}


# ---------------------------------------------------------------- tokens
def _clear_tokens_keep_registration() -> None:
    c = load_credentials()
    if c:
        c.update({"access_token": "", "refresh_token": "", "expires_in": 0, "saved_at_ts": 0})
        _save_credentials(c)


def refresh_tokens() -> dict:
    with _lock:
        c = load_credentials()
        if not c or not c.get("refresh_token"):
            raise AuthError("ChatGPT 로그인이 필요합니다.")
        try:
            r = httpx.post(
                TOKEN_URL,
                data={"grant_type": "refresh_token", "client_id": c["client_id"],
                      "refresh_token": c["refresh_token"], "resource": RESOURCE},
                timeout=30,
            )
        except httpx.HTTPError as e:
            raise AuthError(f"토큰 갱신 중 네트워크 오류: {e}")
        if r.status_code != 200:
            code = ""
            try:
                code = r.json().get("error", "")
            except Exception:
                pass
            if code in ("invalid_grant", "invalid_refresh_token", "token_expired", "refresh_token_expired",
                        "refresh_token_invalidated", "refresh_token_reused", "invalid_client") or r.status_code in (400, 401):
                _clear_tokens_keep_registration()
                raise AuthError("ChatGPT 세션이 만료되었습니다. 설정에서 다시 로그인하세요.")
            raise AuthError(f"토큰 갱신 실패 ({r.status_code}). 잠시 후 다시 시도하세요.")
        tok = r.json()
        c["access_token"] = tok["access_token"]
        c["refresh_token"] = tok.get("refresh_token") or c["refresh_token"]
        c["expires_in"] = int(tok.get("expires_in", 3600))
        if tok.get("scope"):
            c["scopes"] = tok["scope"].split()
        if tok.get("id_token"):
            c["id_token"] = tok["id_token"]
        c["saved_at"] = datetime.now(timezone.utc).isoformat()
        c["saved_at_ts"] = time.time()
        _save_credentials(c)
        return c


def get_access_token(force_refresh: bool = False) -> str:
    c = load_credentials()
    if not c or not c.get("client_id"):
        raise AuthError("ChatGPT 계정으로 로그인하세요 (설정 → ChatGPT 계정).")
    if PLAN_SCOPE not in (c.get("scopes") or []):
        raise AuthError("ChatGPT 플랜 사용 권한이 허용되지 않았습니다. 설정에서 다시 로그인하고 사용 권한에 동의하세요.")
    expires_at = c.get("saved_at_ts", 0) + int(c.get("expires_in", 0))
    if force_refresh or not c.get("access_token") or time.time() > expires_at - 120:
        c = refresh_tokens()
    return c["access_token"]


def logout() -> None:
    with _lock:
        c = load_credentials()
        if not c:
            return
        if c.get("refresh_token"):
            try:
                endpoint = _oidc_config().get("revocation_endpoint")
                if endpoint:
                    httpx.post(endpoint, data={"token": c["refresh_token"], "token_type_hint": "refresh_token",
                                               "client_id": c["client_id"]}, timeout=15)
            except Exception:
                pass
        # keep the registration (client_id) so the next sign-in skips consent
        _save_credentials({"client_id": c.get("client_id", ""), "ext_agent_host_id": c.get("ext_agent_host_id", ""),
                           "email": c.get("email", ""), "scopes": []})


def list_models_sync(access_token: str) -> list[dict]:
    r = httpx.get(f"{RESOURCE}/models", headers={"Authorization": f"Bearer {access_token}"}, timeout=20)
    r.raise_for_status()
    body = r.json()
    items = body.get("models") or body.get("data") or []
    out = []
    for m in items:
        if m.get("visibility", "list") != "list":
            continue
        slug = m.get("slug") or m.get("id")
        if slug:
            out.append({"slug": slug, "display_name": m.get("display_name") or slug})
    return out
