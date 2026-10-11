# AI Voice Service

基于 [OpenBMB/MiniCPM-o-Demo](https://github.com/OpenBMB/MiniCPM-o-Demo) 和
MiniCPM-o 4.5 GGUF 的最小云端实时语音服务。项目保留官方实时 WebSocket 与测试页面，
并额外提供一个便于其他服务调用的 OpenAI 风格文本 REST 接口。

## 对外入口

部署完成后，同一个域名提供：

| 地址 | 用途 |
| --- | --- |
| `https://<domain>/audio_duplex` | 浏览器实时语音测试页 |
| `wss://<domain>/v1/realtime?mode=audio` | 实时音频 WebSocket |
| `https://<domain>/api/v1/chat/completions` | 最小文本 REST 接口 |
| `https://<domain>/api/docs` | Swagger 接口文档 |
| `https://<domain>/api/health` | 聚合健康检查 |

## 服务器要求

- Linux x86_64
- NVIDIA GPU，建议 24GB 显存
- NVIDIA Driver 支持所选 CUDA 版本
- Docker Engine、Docker Compose v2、NVIDIA Container Toolkit
- 一个解析到服务器的域名（浏览器麦克风要求可信 HTTPS）
- 建议至少 16GB 磁盘用于源码、镜像缓存和约 8.3GB 模型权重

RTX 3090 的推荐值已经写入 `.env.example`：CUDA 12.6.3、计算架构 86、Q4_K_M、
8192 上下文。实测全双工加载后显存约 13GB。

## 部署

```bash
git clone https://github.com/string1225/ai-voice-service.git
cd ai-voice-service
cp .env.example .env
```

编辑 `.env`，至少填写：

```dotenv
PUBLIC_DOMAIN=voice.example.com
GGUF_MODEL_HOST_PATH=/opt/models/MiniCPM-o-4_5-gguf
API_KEY=replace-with-a-long-random-secret
```

下载 GGUF 模型：

```bash
MODEL_DIR=/opt/models/MiniCPM-o-4_5-gguf ./scripts/download-model.sh
```

启动：

```bash
docker compose -f compose.cloud.yml up -d --build
docker compose -f compose.cloud.yml ps
docker compose -f compose.cloud.yml logs -f cpp-worker-backend
```

Caddy 会根据 `PUBLIC_DOMAIN` 自动申请并续期 TLS 证书。请提前开放 80/443 端口，
并确保域名 A/AAAA 记录指向服务器。

首次请求会加载模型，文本模式约需 1–2 分钟；首次切换到全双工模式还会重建 duplex
上下文。服务已将 worker 到 C++ 后端的 WebSocket 冷启动容限设为 300 秒。

## REST 调用

```bash
curl https://voice.example.com/api/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "MiniCPM-o-4.5",
    "messages": [{"role": "user", "content": "请只回答：测试"}],
    "max_tokens": 64,
    "temperature": 0.7
  }'
```

当前 REST 层刻意保持最小化：支持非流式文本对话。实时语音、打断、音频输出和视频输入
直接使用 `/v1/realtime` WebSocket；协议说明见 `docs/realtime-protocol-overview.md`。

## 运维

```bash
# 查看状态
curl https://voice.example.com/api/health
nvidia-smi

# 重启
docker compose -f compose.cloud.yml restart

# 停止
docker compose -f compose.cloud.yml down
```

模型、会话数据和证书均通过 volume 管理，不进入 Git。生产环境建议限制 8006、8007、
8080 端口只在 Docker/本机网络可见，仅公开 Caddy 的 80/443，并务必设置 `API_KEY`。

## 开发验证

```bash
python -m pip install -r requirements-api.txt -r requirements-dev.txt
pytest -q tests/test_service_api.py
docker compose --env-file .env.example -f compose.cloud.yml config
```

官方 Demo 的原始说明保存在 `docs/upstream/`。导入基线为
`OpenBMB/MiniCPM-o-Demo@47709a9210dfd71afa76c058e017fc8c4db5c8d2`。
