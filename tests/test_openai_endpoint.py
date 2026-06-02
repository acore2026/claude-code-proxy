import asyncio
from types import SimpleNamespace

from starlette.responses import StreamingResponse

from src.api.endpoints import create_chat_completion


class FakeRequest:
    def __init__(self, llm_client):
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                llm_client=llm_client,
                provider_mode="test",
                w3_oauth_manager=None,
            )
        )

    async def is_disconnected(self):
        return False


class FakeLLMClient:
    def __init__(self):
        self.non_stream_request = None
        self.stream_request = None

    async def create_chat_completion(self, request, request_id=None):
        self.non_stream_request = request
        return {
            "id": "chatcmpl_test",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
        }

    async def create_chat_completion_stream(self, request, request_id=None):
        self.stream_request = request
        yield 'data: {"choices":[{"delta":{"content":"ok"}}]}'
        yield "data: [DONE]"

    def classify_openai_error(self, error_detail):
        return str(error_detail)

    def cancel_request(self, request_id):
        return False


def test_openai_chat_completions_non_streaming():
    async def run_test():
        fake = FakeLLMClient()
        response = await create_chat_completion(
            {
                "model": "MiniMax-M2.7",
                "messages": [{"role": "user", "content": "hello"}],
            },
            FakeRequest(fake),
        )

        assert response["id"] == "chatcmpl_test"
        assert fake.non_stream_request["messages"][0]["content"] == "hello"

    asyncio.run(run_test())


def test_openai_chat_completions_streaming():
    async def run_test():
        fake = FakeLLMClient()
        response = await create_chat_completion(
            {
                "model": "MiniMax-M2.7",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            },
            FakeRequest(fake),
        )

        assert isinstance(response, StreamingResponse)
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

        assert "data: [DONE]" in "".join(chunks)
        assert fake.stream_request["stream"] is True

    asyncio.run(run_test())
