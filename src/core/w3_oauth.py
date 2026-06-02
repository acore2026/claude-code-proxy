import asyncio
import http.client
import json
import logging
import os
import secrets
import ssl
import subprocess
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class W3OAuthCredentials:
    access: str
    refresh: str
    expires: float

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "W3OAuthCredentials":
        return cls(
            access=str(data["access"]),
            refresh=str(data["refresh"]),
            expires=float(data.get("expires", 0)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"access": self.access, "refresh": self.refresh, "expires": self.expires}


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
        return "microsoft" in release or "wsl" in release
    except OSError:
        return False


def generate_client_code() -> str:
    return secrets.token_hex(16)


def build_authorize_url(
    auth_url: str,
    client_id: str,
    callback_url_base: str,
    scope: str,
    client_code: str,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": f"{callback_url_base}?client_code={client_code}",
        "scope": scope,
        "response_type": "code",
        "scope_resource": "devuc",
    }
    return auth_url + "?" + urllib.parse.urlencode(params)


def run_browser_command(command: List[str]) -> bool:
    try:
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
        return True
    except OSError:
        return False


def open_auth_url(auth_url: str) -> bool:
    if is_wsl():
        encoded_url = urllib.parse.quote(auth_url, safe=":/?&=%#")
        for command in (
            ["powershell.exe", "-NoProfile", "-Command", "Start-Process", auth_url],
            ["cmd.exe", "/C", "start", "", auth_url],
            ["wslview", auth_url],
            ["explorer.exe", encoded_url],
        ):
            if run_browser_command(command):
                return True

    try:
        return bool(webbrowser.open(auth_url))
    except webbrowser.Error:
        return False


def ssl_context(verify_tls: bool) -> ssl.SSLContext:
    if verify_tls:
        return ssl.create_default_context()
    return ssl._create_unverified_context()


def parse_https_url(url: str) -> Tuple[str, int, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Only https URLs are supported for W3 OAuth")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return parsed.hostname or "", parsed.port or 443, path


def request_json(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
    verify_tls: bool = False,
) -> Tuple[int, Dict[str, Any]]:
    host, port, path = parse_https_url(url)
    body = None
    request_headers = dict(headers or {})

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
        request_headers["Content-Length"] = str(len(body))

    conn = http.client.HTTPSConnection(
        host,
        port=port,
        timeout=timeout,
        context=ssl_context(verify_tls),
    )
    try:
        conn.request(method, path, body=body, headers=request_headers)
        response = conn.getresponse()
        text = response.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(text) if text else {}
        except json.JSONDecodeError:
            data = {"raw": text}
        return response.status, data
    finally:
        conn.close()


class W3OAuthManager:
    def __init__(self, config):
        self.config = config
        self.credentials: Optional[W3OAuthCredentials] = None
        self.last_error: Optional[str] = None
        self.authenticated = False
        self._lock = asyncio.Lock()

    def load_credentials(self) -> Optional[W3OAuthCredentials]:
        token_path = self.config.w3_token_file
        if not token_path.exists():
            return None
        try:
            return W3OAuthCredentials.from_dict(
                json.loads(token_path.read_text(encoding="utf-8"))
            )
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = f"Could not load W3 token file: {exc}"
            logger.warning(self.last_error)
            return None

    def save_credentials(self, credentials: W3OAuthCredentials) -> None:
        token_path = self.config.w3_token_file
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(json.dumps(credentials.to_dict(), indent=2), encoding="utf-8")
        try:
            os.chmod(token_path, 0o600)
        except OSError:
            pass

    def expires_soon(self, credentials: W3OAuthCredentials) -> bool:
        return time.time() + self.config.w3_refresh_skew_seconds >= credentials.expires

    def token_expiry_seconds(self) -> Optional[int]:
        if not self.credentials:
            return None
        return max(0, int(self.credentials.expires - time.time()))

    async def ensure_access_token(self) -> str:
        async with self._lock:
            credentials = self.credentials or self.load_credentials()
            if credentials and not self.expires_soon(credentials):
                self.credentials = credentials
                self.authenticated = True
                self.last_error = None
                return credentials.access

            if credentials and credentials.refresh:
                try:
                    self.credentials = await self._refresh(credentials)
                    self.save_credentials(self.credentials)
                    self.authenticated = True
                    self.last_error = None
                    return self.credentials.access
                except Exception as exc:
                    self.last_error = f"W3 token refresh failed: {exc}"
                    logger.warning(self.last_error)

            self.credentials = await self._login()
            self.save_credentials(self.credentials)
            self.authenticated = True
            self.last_error = None
            return self.credentials.access

    async def force_refresh(self) -> str:
        async with self._lock:
            credentials = self.credentials or self.load_credentials()
            if not credentials or not credentials.refresh:
                self.credentials = await self._login()
            else:
                self.credentials = await self._refresh(credentials)
            self.save_credentials(self.credentials)
            self.authenticated = True
            self.last_error = None
            return self.credentials.access

    async def _login(self) -> W3OAuthCredentials:
        client_code = generate_client_code()
        auth_url = build_authorize_url(
            self.config.w3_auth_url,
            self.config.w3_client_id,
            self.config.w3_callback_url_base,
            self.config.w3_scope,
            client_code,
        )
        print("Open this URL to authenticate W3 SSO:")
        print(auth_url)
        print("")

        if self.config.w3_open_browser and not open_auth_url(auth_url):
            print("Could not open a browser automatically. Use the URL above.")

        return await asyncio.to_thread(self._poll_for_token, client_code)

    def _poll_for_token(self, client_code: str) -> W3OAuthCredentials:
        callback_url = f"{self.config.w3_callback_url_base}?client_code={client_code}"
        payload = {"clientCode": client_code, "redirectUrl": callback_url}
        attempts = max(1, int(self.config.w3_auth_timeout_seconds))

        for _ in range(attempts):
            status, data = request_json(
                self.config.w3_token_url,
                method="POST",
                payload=payload,
                timeout=self.config.request_timeout,
                verify_tls=self.config.w3_verify_tls,
            )
            if 200 <= status < 300 and data.get("access_token") and data.get("refresh_token"):
                expires_in = int(data.get("expires_in") or 3600)
                return W3OAuthCredentials(
                    access=str(data["access_token"]),
                    refresh=str(data["refresh_token"]),
                    expires=time.time() + expires_in,
                )
            time.sleep(1)

        raise TimeoutError("W3 OAuth login timed out")

    async def _refresh(self, credentials: W3OAuthCredentials) -> W3OAuthCredentials:
        return await asyncio.to_thread(self._refresh_sync, credentials)

    def _refresh_sync(self, credentials: W3OAuthCredentials) -> W3OAuthCredentials:
        status, data = request_json(
            self.config.w3_refresh_url,
            method="POST",
            headers={"x-refresh-token": credentials.refresh},
            timeout=self.config.request_timeout,
            verify_tls=self.config.w3_verify_tls,
        )
        if status < 200 or status >= 300:
            raise RuntimeError(f"HTTP {status}: {data}")
        if not data.get("access_token"):
            raise RuntimeError("No access_token in refresh response")

        return W3OAuthCredentials(
            access=str(data["access_token"]),
            refresh=str(data.get("refresh_token") or credentials.refresh),
            expires=time.time() + 70 * 3600,
        )
