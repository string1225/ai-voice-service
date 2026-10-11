from fastapi.testclient import TestClient

import service_api


def test_models_endpoint():
    client = TestClient(service_api.app)
    response = client.get("/v1/models")
    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == "MiniCPM-o-4.5"


def test_chat_completion(monkeypatch):
    async def fake_chat(request):
        assert request.messages[-1].content == "ping"
        return "pong"

    monkeypatch.setattr(service_api, "_chat_via_gateway", fake_chat)
    client = TestClient(service_api.app)
    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "ping"}]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "pong"
    assert payload["object"] == "chat.completion"


def test_streaming_is_explicitly_rejected():
    client = TestClient(service_api.app)
    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "ping"}], "stream": True},
    )
    assert response.status_code == 400
