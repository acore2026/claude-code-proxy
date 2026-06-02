import asyncio
import http.client
import json
import uuid
from fastapi import HTTPException
from typing import Any, AsyncGenerator, Dict, Optional, Tuple

from src.core.w3_oauth import W3OAuthManager, parse_https_url, ssl_context


class W3MiniMaxClient:
    """OpenAI-compatible W3 MiniMax client with OAuth token refresh."""

    def __init__(self, config, oauth_manager: W3OAuthManager):
        self.config = config
        self.oauth_manager = oauth_manager
        self.active_requests: Dict[str, asyncio.Event] = {}

    def chat_completions_url(self) -> str:
        return self.config.w3_api_base_url.rstrip("/") + "/chat/completions"

    def classify_openai_error(self, error_detail: Any) -> str:
        error_str = str(error_detail).lower()
        if "401" in error_str or "403" in error_str or "unauthorized" in error_str:
            return "W3 OAuth token is invalid or expired. The proxy will refresh and retry when possible."
        if "timeout" in error_str:
            return "W3 provider request timed out."
        return str(error_detail)

    def cancel_request(self, request_id: str) -> bool:
        if request_id in self.active_requests:
            self.active_requests[request_id].set()
            return True
        return False

    async def create_chat_completion(
        self, request: Dict[str, Any], request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        if request_id:
            self.active_requests[request_id] = asyncio.Event()

        try:
            token = await self.oauth_manager.ensure_access_token()
            status, data = await asyncio.to_thread(self._post_json, request, token)

            if status in (401, 403):
                token = await self.oauth_manager.force_refresh()
                status, data = await asyncio.to_thread(self._post_json, request, token)

            if status < 200 or status >= 300:
                raise HTTPException(status_code=status, detail=data)

            return data
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Unexpected W3 error: {exc}")
        finally:
            if request_id and request_id in self.active_requests:
                del self.active_requests[request_id]

    async def create_chat_completion_stream(
        self, request: Dict[str, Any], request_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        self.prepare_stream_request(request)

        if request_id:
            self.active_requests[request_id] = asyncio.Event()

        conn: Optional[http.client.HTTPSConnection] = None
        response: Optional[http.client.HTTPResponse] = None

        try:
            token = await self.oauth_manager.ensure_access_token()
            conn, response = await asyncio.to_thread(self._open_stream, request, token)

            if response.status in (401, 403):
                await asyncio.to_thread(conn.close)
                token = await self.oauth_manager.force_refresh()
                conn, response = await asyncio.to_thread(self._open_stream, request, token)

            if response.status < 200 or response.status >= 300:
                error_body = await asyncio.to_thread(response.read)
                raise HTTPException(
                    status_code=response.status,
                    detail=error_body.decode("utf-8", errors="replace")[:500],
                )

            while True:
                cancel_event = self.active_requests.get(request_id) if request_id else None
                if cancel_event and cancel_event.is_set():
                    raise HTTPException(status_code=499, detail="Request cancelled by client")

                raw = await asyncio.to_thread(response.readline)
                if not raw:
                    break

                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    yield line if line.startswith("data:") else f"data: {line}"

            yield "data: [DONE]"
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Unexpected W3 streaming error: {exc}")
        finally:
            if conn:
                await asyncio.to_thread(conn.close)
            if request_id and request_id in self.active_requests:
                del self.active_requests[request_id]

    def _post_json(self, request: Dict[str, Any], token: str) -> Tuple[int, Dict[str, Any]]:
        body = json.dumps(request, ensure_ascii=False).encode("utf-8")
        conn = self._make_connection()
        try:
            conn.request(
                "POST",
                self._chat_path(),
                body=body,
                headers=self._headers(token, len(body)),
            )
            response = conn.getresponse()
            text = response.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(text) if text else {}
            except json.JSONDecodeError:
                data = {"raw": text}
            return response.status, data
        finally:
            conn.close()

    def prepare_stream_request(self, request: Dict[str, Any]) -> None:
        request["stream"] = True
        request.pop("stream_options", None)

    def _open_stream(
        self, request: Dict[str, Any], token: str
    ) -> Tuple[http.client.HTTPSConnection, http.client.HTTPResponse]:
        body = json.dumps(request, ensure_ascii=False).encode("utf-8")
        conn = self._make_connection()
        try:
            conn.request(
                "POST",
                self._chat_path(),
                body=body,
                headers=self._headers(token, len(body)),
            )
            return conn, conn.getresponse()
        except Exception:
            conn.close()
            raise

    def _make_connection(self) -> http.client.HTTPSConnection:
        host, port, _ = parse_https_url(self.chat_completions_url())
        return http.client.HTTPSConnection(
            host,
            port=port,
            timeout=self.config.request_timeout,
            context=ssl_context(self.config.w3_verify_tls),
        )

    def _chat_path(self) -> str:
        _, _, path = parse_https_url(self.chat_completions_url())
        return path

    def _headers(self, token: str, content_length: int) -> Dict[str, str]:
        headers = self.config.get_custom_headers()
        headers.update(
            {
                "Content-Type": "application/json",
                "Content-Length": str(content_length),
                "User-Agent": "claude-proxy/1.1.0",
                "X-Auth-Token": token,
                "X-Provider-ID": self.config.w3_provider_id,
                "X-Request-ID": str(uuid.uuid4()),
            }
        )
        return headers
