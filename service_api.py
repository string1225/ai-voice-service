"""Small public REST facade for the MiniCPM-o realtime gateway."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import time
import uuid
from typing import Literal

import httpx
import websockets
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


GATEWAY_HTTP_URL = os.getenv("GATEWAY_HTTP_URL", "http://gateway:8006").rstrip("/")
GATEWAY_WS_URL = os.getenv("GATEWAY_WS_URL", "ws://gateway:8006/v1/realtime").rstrip("?")
CHAT_TIMEOUT_SECONDS = float(os.getenv("CHAT_TIMEOUT_SECONDS", "360"))
API_KEY = os.getenv("API_KEY", "").strip()


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class ChatCompletionRequest(BaseModel):
    model: str = "MiniCPM-o-4.5"
    messages: list[ChatMessage] = Field(min_length=1)
    max_tokens: int = Field(default=128, ge=1, le=2048)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    stream: bool = False


async def require_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> None:
    """Require a configured key while allowing keyless local development."""
    if not API_KEY:
        return
    bearer = ""
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    supplied = bearer or (x_api_key or "")
    if not supplied or not hmac.compare_digest(supplied, API_KEY):
        raise HTTPException(status_code=401, detail="invalid API key")


def _cors_origins() -> list[str]:
    value = os.getenv("ALLOWED_ORIGINS", "*").strip()
    return [item.strip() for item in value.split(",") if item.strip()] or ["*"]


app = FastAPI(
    title="MiniCPM-o Voice Service",
    version="0.1.0",
    description="Minimal REST facade; realtime audio is available at /v1/realtime.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


async def _receive_json(ws) -> dict:
    raw = await ws.recv()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    message = json.loads(raw)
    if not isinstance(message, dict):
        raise RuntimeError("gateway returned a non-object message")
    return message


async def _chat_via_gateway(request: ChatCompletionRequest) -> str:
    url = f"{GATEWAY_WS_URL}?mode=chat"
    created = False
    text_parts: list[str] = []

    async with websockets.connect(
        url,
        max_size=128 * 1024 * 1024,
        open_timeout=30,
        ping_timeout=300,
    ) as ws:
        try:
            while not created:
                message = await asyncio.wait_for(_receive_json(ws), CHAT_TIMEOUT_SECONDS)
                message_type = message.get("type")
                if message_type in {"session.queue_done", "queue_done"}:
                    await ws.send(json.dumps({"type": "session.init", "payload": {}}))
                elif message_type == "session.created":
                    created = True
                elif message_type == "error":
                    raise RuntimeError(str(message.get("error") or message))

            payload = {
                "messages": [message.model_dump() for message in request.messages],
                "streaming": False,
                "generation": {
                    "max_new_tokens": request.max_tokens,
                    "temperature": request.temperature,
                },
                "image": {"max_slice_nums": 1},
                "omni_mode": False,
                "tts": {"enabled": False},
                "use_tts_template": False,
            }
            await ws.send(json.dumps({"type": "input.append", "input": payload}, ensure_ascii=False))

            while True:
                message = await asyncio.wait_for(_receive_json(ws), CHAT_TIMEOUT_SECONDS)
                message_type = message.get("type")
                if message_type == "response.output.delta" and message.get("kind") == "text":
                    text_parts.append(str(message.get("text") or ""))
                elif message_type == "response.done":
                    return str(message.get("text") or "".join(text_parts))
                elif message_type == "error":
                    raise RuntimeError(str(message.get("error") or message))
                elif message_type == "session.closed":
                    raise RuntimeError(f"session closed before response: {message.get('reason', 'unknown')}")
        finally:
            if created:
                try:
                    await ws.send(json.dumps({"type": "session.close", "reason": "rest_complete"}))
                except Exception:
                    pass


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index() -> str:
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>MiniCPM-o API Test</title><style>
body{font:16px system-ui;max-width:760px;margin:40px auto;padding:0 18px;background:#111827;color:#e5e7eb}
textarea,input,button,pre{box-sizing:border-box;width:100%;margin:8px 0;padding:12px;border-radius:8px}
textarea,input{background:#1f2937;color:#fff;border:1px solid #4b5563}button{cursor:pointer;background:#2563eb;color:#fff;border:0}
pre{white-space:pre-wrap;background:#030712;min-height:80px}a{color:#60a5fa}</style></head><body>
<h1>MiniCPM-o 4.5</h1><p><a href="audio_duplex">打开实时语音测试页</a> · <a href="docs">Swagger API</a></p>
<input id="key" type="password" placeholder="API Key（未配置时留空）"><textarea id="prompt">请只回答：测试</textarea>
<button onclick="run()">发送文本测试</button><pre id="out">等待请求</pre><script>
async function run(){const out=document.querySelector('#out'),key=document.querySelector('#key').value;
 const prefix=location.pathname.startsWith('/api')?'/api':'';out.textContent='请求中，首次冷启动可能需要数分钟…';
 try{const r=await fetch(prefix+'/v1/chat/completions',{method:'POST',headers:{'Content-Type':'application/json',...(key?{'Authorization':'Bearer '+key}:{})},body:JSON.stringify({messages:[{role:'user',content:document.querySelector('#prompt').value}]})});out.textContent=JSON.stringify(await r.json(),null,2)}catch(e){out.textContent=String(e)}}
</script></body></html>"""


@app.get("/health")
async def health() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            gateway_health = await client.get(f"{GATEWAY_HTTP_URL}/health")
            gateway_status = await client.get(f"{GATEWAY_HTTP_URL}/status")
        gateway_health.raise_for_status()
        gateway_status.raise_for_status()
        status = gateway_status.json()
        return {
            "status": "healthy" if status.get("total_workers", 0) > 0 else "degraded",
            "gateway": gateway_health.json(),
            "workers": status,
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"gateway unavailable: {exc}") from exc


@app.get("/v1/models", dependencies=[Depends(require_api_key)])
async def models() -> dict:
    return {
        "object": "list",
        "data": [{"id": "MiniCPM-o-4.5", "object": "model", "owned_by": "OpenBMB"}],
    }


@app.post("/v1/chat/completions", dependencies=[Depends(require_api_key)])
async def chat_completions(request: ChatCompletionRequest) -> dict:
    if request.stream:
        raise HTTPException(status_code=400, detail="stream=true is not supported by the minimal REST facade")
    try:
        content = await _chat_via_gateway(request)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="model response timed out") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"gateway request failed: {exc}") from exc

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": None,
    }
