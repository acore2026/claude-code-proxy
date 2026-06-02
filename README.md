# Claude Code Proxy for Huawei W3 MiniMax

A W3 OAuth-focused fork of the original Claude Code Proxy. It lets Claude Code
and OpenAI-compatible clients use Huawei W3 SSO to call the internal MiniMax
chat completions endpoint without manually copying access tokens.

The proxy starts in W3 mode by default through the committed `.env.w3` file,
opens or prints the SSO login URL on first run, stores the OAuth credentials,
and refreshes tokens automatically before they expire.

## Features

- Huawei W3 SSO OAuth login on startup
- Automatic token cache and refresh
- WSL-aware browser opening for local login
- Claude Messages API endpoint for Claude Code: `/v1/messages`
- OpenAI Chat Completions endpoint: `/v1/chat/completions`
- Streaming SSE support for both API shapes
- Tool/function-call passthrough
- Docker image that bundles the W3 default env file
- GitHub Actions workflow for publishing a GHCR Docker image

## Quick Start

### Docker

```bash
docker build -t claude-code-proxy:w3 .
docker run --rm -p 8082:8082 -v claude-code-proxy-w3:/data claude-code-proxy:w3
```

The image bundles `.env.w3`, so W3 mode is enabled without passing an env file.
The `-v claude-code-proxy-w3:/data` volume is optional but recommended so OAuth
credentials survive container restarts. On first startup, copy the printed W3
SSO URL into your browser. Later starts reuse and refresh the cached token
automatically.

### Local Python

```bash
uv sync
uv run claude-code-proxy
```

If `.env` does not exist, the app loads `.env.w3` as the default environment.
Create `.env` only when you want local overrides.

## Using The Proxy

### Claude Code

```bash
ANTHROPIC_BASE_URL=http://localhost:8082 ANTHROPIC_API_KEY=any-value claude
```

If you set `ANTHROPIC_API_KEY` in the proxy environment, clients must send that
exact value. If it is unset, client API key validation is disabled.

### OpenAI-Compatible Clients

```bash
curl http://localhost:8082/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "MiniMax-M2.7",
    "messages": [{"role": "user", "content": "hello"}],
    "stream": false
  }'
```

Streaming also uses the standard OpenAI-compatible request shape:

```bash
curl -N http://localhost:8082/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "MiniMax-M2.7",
    "messages": [{"role": "user", "content": "write a short haiku"}],
    "stream": true
  }'
```

## Configuration

The committed `.env.w3` is the default configuration:

```env
W3_OAUTH_ENABLED=true
W3_API_BASE_URL=https://codeagentcli.rnd.huawei.com/codeAgentPro
W3_MODEL=MiniMax-M2.7
W3_TOKEN_FILE=/data/.hw_minimax_oauth.json
W3_OPEN_BROWSER=false
W3_VERIFY_TLS=false
BIG_MODEL=MiniMax-M2.7
MIDDLE_MODEL=MiniMax-M2.7
SMALL_MODEL=MiniMax-M2.7
```

Important variables:

| Variable | Purpose |
| --- | --- |
| `W3_OAUTH_ENABLED` | Enables W3 OAuth provider mode. |
| `W3_TOKEN_FILE` | OAuth credential cache path. |
| `W3_OPEN_BROWSER` | Opens the SSO URL automatically. Defaults to true on WSL if not set. |
| `W3_VERIFY_TLS` | Enables normal CA verification. Default is false for Huawei internal PKI compatibility. |
| `W3_REFRESH_SKEW_SECONDS` | Refresh window before token expiry. |
| `W3_AUTH_TIMEOUT_SECONDS` | Startup login polling timeout. |
| `ANTHROPIC_API_KEY` | Optional client-side API key expected by the proxy. |

For Docker, keep `W3_TOKEN_FILE=/data/.hw_minimax_oauth.json` and mount `/data`
if you want tokens to persist outside the container.

## Endpoints

| Endpoint | Shape | Purpose |
| --- | --- | --- |
| `POST /v1/messages` | Claude Messages | Claude Code compatibility. |
| `POST /v1/messages/count_tokens` | Claude token count | Lightweight character-based estimate. |
| `POST /v1/chat/completions` | OpenAI Chat Completions | Direct OpenAI-compatible access to W3 MiniMax. |
| `GET /health` | JSON | Health, provider mode, and W3 token status. |
| `GET /test-connection` | JSON | Sends a small test request through the active provider. |

## Docker Image Releases

The workflow at `.github/workflows/release-image.yml` publishes to GitHub
Container Registry as:

```text
ghcr.io/<owner>/<repo>
```

Publish `v1`:

```bash
git tag v1
git push origin v1
```

The workflow also runs when a GitHub release is published, and it can be run
manually from GitHub Actions with the default `version` input set to `v1`.

## Development

```bash
uv sync
W3_OAUTH_ENABLED=false OPENAI_API_KEY=sk-test uv run pytest -q tests/test_w3_oauth.py
W3_OAUTH_ENABLED=false OPENAI_API_KEY=sk-test uv run python -m compileall src tests examples
uv build
docker build -t claude-code-proxy:w3-test .
```

The repository still keeps the original OpenAI-compatible provider path for
development and fallback use, but this fork is intended to be deployed as the W3
OAuth MiniMax proxy.
