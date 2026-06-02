import json
import time
from pathlib import Path
from types import SimpleNamespace

from src.core.w3_client import W3MiniMaxClient
from src.core.w3_oauth import W3OAuthCredentials, W3OAuthManager, build_authorize_url


def make_config(tmp_path: Path):
    return SimpleNamespace(
        request_timeout=30,
        w3_api_base_url="https://codeagentcli.rnd.huawei.com/codeAgentPro",
        w3_auth_url="https://login.example.com/oauth2/authorize",
        w3_token_url="https://api.example.com/oauth/getToken",
        w3_refresh_url="https://api.example.com/oauth/refreshToken",
        w3_client_id="client-id",
        w3_callback_url_base="https://api.example.com/oauth/callback",
        w3_scope="1000:1002",
        w3_provider_id="hw-minimax",
        w3_token_file=tmp_path / "token.json",
        w3_verify_tls=False,
        w3_open_browser=False,
        w3_refresh_skew_seconds=300,
        w3_auth_timeout_seconds=300,
        get_custom_headers=lambda: {},
    )


def test_build_authorize_url_contains_oauth_parameters():
    url = build_authorize_url(
        "https://login.example.com/oauth2/authorize",
        "client-id",
        "https://api.example.com/oauth/callback",
        "1000:1002",
        "abc123",
    )

    assert "client_id=client-id" in url
    assert "response_type=code" in url
    assert "scope=1000%3A1002" in url
    assert "scope_resource=devuc" in url
    assert "client_code%3Dabc123" in url


def test_token_file_save_load_and_expiry(tmp_path):
    config = make_config(tmp_path)
    manager = W3OAuthManager(config)
    credentials = W3OAuthCredentials(access="access", refresh="refresh", expires=time.time() + 60)

    manager.save_credentials(credentials)
    loaded = manager.load_credentials()

    assert json.loads(config.w3_token_file.read_text(encoding="utf-8"))["access"] == "access"
    assert loaded == credentials
    assert manager.expires_soon(credentials)


def test_w3_client_headers_include_oauth_and_provider(tmp_path):
    config = make_config(tmp_path)
    manager = W3OAuthManager(config)
    client = W3MiniMaxClient(config, manager)

    headers = client._headers("access-token", 123)

    assert headers["X-Auth-Token"] == "access-token"
    assert headers["X-Provider-ID"] == "hw-minimax"
    assert headers["Content-Length"] == "123"


def test_w3_stream_request_removes_stream_options(tmp_path):
    config = make_config(tmp_path)
    manager = W3OAuthManager(config)
    client = W3MiniMaxClient(config, manager)
    request = {"model": "MiniMax-M2.7", "messages": [], "stream_options": {"include_usage": True}}

    client.prepare_stream_request(request)

    assert request["stream"] is True
    assert "stream_options" not in request
