import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

from orzchat_bot.llm import ChatCompletionClient, _message_text


class FakeChatHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        FakeChatHandler.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": body,
            }
        )
        payload = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "  Hello from the model.  "},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        pass


async def test_chat_completion_request_and_response():
    FakeChatHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    client = ChatCompletionClient(
        base_url=f"http://127.0.0.1:{port}/v1",
        api_key="test-key",
        model="test-model",
        temperature=0.2,
        max_tokens=123,
        timeout=5,
    )
    try:
        reply = await client.complete(
            [
                {"role": "system", "content": "be nice"},
                {"role": "user", "content": "hi"},
            ]
        )
    finally:
        await client.close()
        server.shutdown()
        server.server_close()

    assert reply == "Hello from the model."
    assert len(FakeChatHandler.requests) == 1
    request = FakeChatHandler.requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["authorization"] == "Bearer test-key"
    body = request["body"]
    assert isinstance(body, dict)
    assert body["model"] == "test-model"
    assert body["temperature"] == 0.2
    assert body["max_tokens"] == 123
    assert body["messages"][-1] == {"role": "user", "content": "hi"}


def test_multipart_content_is_joined():
    message = SimpleNamespace(
        content=[
            {"type": "text", "text": "one "},
            SimpleNamespace(text="two"),
            "three",
        ]
    )
    assert _message_text(message) == "one twothree"


def test_empty_content_is_text_empty():
    assert _message_text(SimpleNamespace(content=None)) == ""
    assert _message_text(SimpleNamespace(content=[])) == ""


def test_construction_survives_malformed_no_proxy(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,::1,[::1]")
    client = ChatCompletionClient(
        base_url="http://127.0.0.1:1/v1",
        api_key="x",
        model="m",
        timeout=2,
    )
    asyncio.run(client.close())
