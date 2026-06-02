#!/usr/bin/env python3
"""Minimal Huawei W3 OAuth + MiniMax streaming chat CLI.

This is a Python translation of the TypeScript pi-ai provider example. It keeps
the same W3 SSO login, token refresh, and streaming chat completion behavior,
but exposes it as a small command-line app.
"""

import argparse
import http.client
import json
import os
import secrets
import ssl
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


API_BASE_URL = "https://codeagentcli.rnd.huawei.com/codeAgentPro"

OAUTH_CONFIG = {
    "auth_url": (
        "https://ssoproxysvr.cd-cloud-ssoproxysvr.szv.dragon.tools.huawei.com/"
        "ssoproxysvr/oauth2/authorize"
    ),
    "token_url": API_BASE_URL + "/oauth/getToken",
    "refresh_url": API_BASE_URL + "/oauth/refreshToken",
    "client_id": "com.huawei.devmind.codebot.apibot",
    "callback_url_base": API_BASE_URL + "/oauth/callback",
    "scope": "1000:1002",
}

POLL_INTERVAL_SECONDS = 1
MAX_POLL_ATTEMPTS = 300
MODEL_ID = "MiniMax-M2.7"
PROVIDER_ID = "hw-minimax"
DEFAULT_TOKEN_PATH = Path.home() / ".hw_minimax_oauth.json"


@dataclass
class OAuthCredentials:
    access: str
    refresh: str
    expires: float

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OAuthCredentials":
        return cls(
            access=str(data["access"]),
            refresh=str(data["refresh"]),
            expires=float(data.get("expires", 0)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"access": self.access, "refresh": self.refresh, "expires": self.expires}

    def expires_soon(self, skew_seconds: int = 60) -> bool:
        return time.time() + skew_seconds >= self.expires


def generate_client_code() -> str:
    return secrets.token_hex(16)


def build_authorize_url(client_code: str) -> str:
    params = {
        "client_id": OAUTH_CONFIG["client_id"],
        "redirect_uri": OAUTH_CONFIG["callback_url_base"] + "?client_code=" + client_code,
        "scope": OAUTH_CONFIG["scope"],
        "response_type": "code",
        "scope_resource": "devuc",
    }
    return OAUTH_CONFIG["auth_url"] + "?" + urllib.parse.urlencode(params)


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
        return "microsoft" in release or "wsl" in release
    except OSError:
        return False


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
    """Open an auth URL, preferring the Windows host browser when running in WSL."""
    if is_wsl():
        encoded_url = urllib.parse.quote(auth_url, safe=":/?&=%#")
        wsl_commands = [
            ["powershell.exe", "-NoProfile", "-Command", "Start-Process", auth_url],
            ["cmd.exe", "/C", "start", "", auth_url],
            ["wslview", auth_url],
            ["explorer.exe", encoded_url],
        ]
        for command in wsl_commands:
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


def parse_url(url: str) -> Tuple[str, int, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Only https URLs are supported")
    port = parsed.port or 443
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return parsed.hostname or "", port, path


def request_bytes(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[bytes] = None,
    timeout: int = 30,
    verify_tls: bool = False,
) -> Tuple[int, Dict[str, str], bytes]:
    host, port, path = parse_url(url)
    conn = http.client.HTTPSConnection(
        host,
        port=port,
        timeout=timeout,
        context=ssl_context(verify_tls),
    )
    try:
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        response_headers = {k.lower(): v for k, v in response.getheaders()}
        return response.status, response_headers, response.read()
    finally:
        conn.close()


def request_json(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
    verify_tls: bool = False,
) -> Tuple[int, Dict[str, str], Dict[str, Any]]:
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
        request_headers["Content-Length"] = str(len(body))

    status, response_headers, response_body = request_bytes(
        url,
        method=method,
        headers=request_headers,
        body=body,
        timeout=timeout,
        verify_tls=verify_tls,
    )
    text = response_body.decode("utf-8", errors="replace")
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        data = {"raw": text}
    return status, response_headers, data


def poll_for_token(client_code: str, verify_tls: bool = False) -> OAuthCredentials:
    callback_url = OAUTH_CONFIG["callback_url_base"] + "?client_code=" + client_code
    payload = {"clientCode": client_code, "redirectUrl": callback_url}

    for _ in range(MAX_POLL_ATTEMPTS):
        status, _, data = request_json(
            OAUTH_CONFIG["token_url"],
            method="POST",
            payload=payload,
            timeout=30,
            verify_tls=verify_tls,
        )
        if 200 <= status < 300 and data.get("access_token") and data.get("refresh_token"):
            expires_in = int(data.get("expires_in") or 3600)
            return OAuthCredentials(
                access=str(data["access_token"]),
                refresh=str(data["refresh_token"]),
                expires=time.time() + expires_in,
            )
        time.sleep(POLL_INTERVAL_SECONDS)

    raise TimeoutError("Login timeout - please try again")


def save_credentials(path: Path, credentials: OAuthCredentials) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(credentials.to_dict(), indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_credentials(path: Path) -> OAuthCredentials:
    return OAuthCredentials.from_dict(json.loads(path.read_text(encoding="utf-8")))


def login(token_path: Path, verify_tls: bool = False, open_browser: bool = False) -> OAuthCredentials:
    client_code = generate_client_code()
    auth_url = build_authorize_url(client_code)

    print("Open this URL to authenticate:")
    print(auth_url)
    print()
    print("Waiting for OAuth callback token...")

    if open_browser:
        if not open_auth_url(auth_url):
            print("Could not open a browser automatically. Use the URL above.", file=sys.stderr)

    credentials = poll_for_token(client_code, verify_tls=verify_tls)
    save_credentials(token_path, credentials)
    print("Login succeeded. Token saved to " + str(token_path))
    return credentials


def refresh_token(credentials: OAuthCredentials, verify_tls: bool = False) -> OAuthCredentials:
    status, _, data = request_json(
        OAUTH_CONFIG["refresh_url"],
        method="POST",
        headers={"x-refresh-token": credentials.refresh},
        timeout=30,
        verify_tls=verify_tls,
    )
    if status < 200 or status >= 300:
        raise RuntimeError("Token refresh failed: HTTP {0}: {1}".format(status, data))
    if not data.get("access_token"):
        raise RuntimeError("No access_token in refresh response")

    return OAuthCredentials(
        access=str(data["access_token"]),
        refresh=str(data.get("refresh_token") or credentials.refresh),
        expires=time.time() + 70 * 3600,
    )


def get_credentials(token_path: Path, verify_tls: bool = False) -> OAuthCredentials:
    if not token_path.exists():
        raise FileNotFoundError("No token file found. Run login first.")

    credentials = load_credentials(token_path)
    if credentials.expires_soon():
        credentials = refresh_token(credentials, verify_tls=verify_tls)
        save_credentials(token_path, credentials)
    return credentials


def sanitize_surrogates(text: str) -> str:
    return "".join(ch for ch in text if not 0xD800 <= ord(ch) <= 0xDFFF)


def build_messages(prompt: str, system_prompt: Optional[str] = None) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": sanitize_surrogates(system_prompt)})
    messages.append({"role": "user", "content": sanitize_surrogates(prompt)})
    return messages


def stream_lines(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout: int = 60,
    verify_tls: bool = False,
) -> Iterable[str]:
    host, port, path = parse_url(url)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = dict(headers)
    request_headers["Content-Type"] = "application/json"
    request_headers["Content-Length"] = str(len(body))

    conn = http.client.HTTPSConnection(
        host,
        port=port,
        timeout=timeout,
        context=ssl_context(verify_tls),
    )
    try:
        conn.request("POST", path, body=body, headers=request_headers)
        response = conn.getresponse()
        if response.status != 200:
            error_body = response.read().decode("utf-8", errors="replace")
            raise RuntimeError("HTTP {0}: {1}".format(response.status, error_body[:500]))

        while True:
            raw = response.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                yield line
    finally:
        conn.close()


def parse_partial_json(partial: str) -> Any:
    if not partial.strip():
        return {}
    try:
        return json.loads(partial)
    except json.JSONDecodeError:
        return {}


def stream_chat(
    credentials: OAuthCredentials,
    prompt: str,
    system_prompt: Optional[str] = None,
    max_tokens: int = 24576,
    show_thinking: bool = False,
    verify_tls: bool = False,
) -> None:
    payload = {
        "model": MODEL_ID,
        "messages": build_messages(prompt, system_prompt=system_prompt),
        "stream": True,
        "max_tokens": max_tokens,
    }
    headers = {
        "X-Auth-Token": credentials.access,
        "X-Provider-ID": PROVIDER_ID,
    }

    tool_calls: Dict[int, Dict[str, Any]] = {}
    saw_finish_reason = False
    finish_reason = "stop"

    for line in stream_lines(
        API_BASE_URL + "/chat/completions",
        headers=headers,
        payload=payload,
        timeout=60,
        verify_tls=verify_tls,
    ):
        data_line = line
        if data_line.startswith("data:"):
            data_line = data_line[data_line.index(":") + 1 :].strip()
        if data_line == "[DONE]":
            continue

        try:
            chunk = json.loads(data_line)
        except json.JSONDecodeError:
            continue

        choice = (chunk.get("choices") or [{}])[0]
        if choice.get("finish_reason"):
            saw_finish_reason = True
            finish_reason = str(choice["finish_reason"])

        delta = choice.get("delta") or {}
        for field in ("reasoning_content", "reasoning", "reasoning_text"):
            value = delta.get(field)
            if isinstance(value, str) and value:
                if show_thinking:
                    print(value, end="", flush=True)
                break

        content = delta.get("content")
        if isinstance(content, str) and content:
            print(content, end="", flush=True)

        for tool_call in delta.get("tool_calls") or []:
            index = int(tool_call.get("index") or 0)
            state = tool_calls.setdefault(
                index,
                {"id": "", "name": "", "partial_json": ""},
            )
            if tool_call.get("id"):
                state["id"] = tool_call["id"]
            function_data = tool_call.get("function") or {}
            if function_data.get("name"):
                state["name"] = function_data["name"]
            if function_data.get("arguments"):
                state["partial_json"] += function_data["arguments"]

    print()
    if tool_calls:
        normalized_calls = []
        for state in tool_calls.values():
            normalized_calls.append(
                {
                    "id": state["id"],
                    "name": state["name"],
                    "arguments": parse_partial_json(state["partial_json"]),
                    "raw_arguments": state["partial_json"],
                }
            )
        print(json.dumps({"tool_calls": normalized_calls}, indent=2, ensure_ascii=False))

    if not saw_finish_reason:
        raise RuntimeError("Stream ended without finish_reason")
    if finish_reason not in ("stop", "tool_calls", "length"):
        print("Finish reason: " + finish_reason, file=sys.stderr)


def print_status(token_path: Path) -> None:
    if not token_path.exists():
        print("No token file found: " + str(token_path))
        return
    credentials = load_credentials(token_path)
    remaining = int(credentials.expires - time.time())
    print("Token file: " + str(token_path))
    print("Access token: " + credentials.access[:8] + "...")
    print("Refresh token: " + credentials.refresh[:8] + "...")
    print("Expires in: {0} seconds".format(max(0, remaining)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Huawei W3 OAuth MiniMax CLI")
    parser.add_argument(
        "--token-file",
        type=Path,
        default=DEFAULT_TOKEN_PATH,
        help="Path to saved OAuth credentials",
    )
    parser.add_argument(
        "--verify-tls",
        action="store_true",
        help="Use normal CA verification instead of the internal-PKI bypass",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login", help="Start W3 SSO login and save credentials")
    login_parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the auth URL, including the Windows host browser from WSL",
    )

    subparsers.add_parser("refresh", help="Refresh saved credentials")
    subparsers.add_parser("status", help="Show saved credential status")

    chat_parser = subparsers.add_parser("chat", help="Send one streaming chat request")
    chat_parser.add_argument("prompt", help="User prompt")
    chat_parser.add_argument("--system", help="Optional system prompt")
    chat_parser.add_argument("--max-tokens", type=int, default=24576)
    chat_parser.add_argument("--show-thinking", action="store_true")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "login":
            login(args.token_file, verify_tls=args.verify_tls, open_browser=args.open_browser)
        elif args.command == "refresh":
            credentials = refresh_token(load_credentials(args.token_file), verify_tls=args.verify_tls)
            save_credentials(args.token_file, credentials)
            print("Token refreshed.")
        elif args.command == "status":
            print_status(args.token_file)
        elif args.command == "chat":
            credentials = get_credentials(args.token_file, verify_tls=args.verify_tls)
            stream_chat(
                credentials,
                args.prompt,
                system_prompt=args.system,
                max_tokens=args.max_tokens,
                show_thinking=args.show_thinking,
                verify_tls=args.verify_tls,
            )
    except Exception as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
