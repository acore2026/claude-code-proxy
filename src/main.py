import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from src.api.endpoints import router as api_router
from src.core.client import OpenAIClient
from src.core.config import config
from src.core.w3_client import W3MiniMaxClient
from src.core.w3_oauth import W3OAuthManager


async def create_llm_client():
    if config.w3_oauth_enabled:
        oauth_manager = W3OAuthManager(config)
        await oauth_manager.ensure_access_token()
        return W3MiniMaxClient(config, oauth_manager), oauth_manager, "w3"

    custom_headers = config.get_custom_headers()
    return (
        OpenAIClient(
            config.openai_api_key or "",
            config.openai_base_url,
            config.request_timeout,
            api_version=config.azure_api_version,
            custom_headers=custom_headers,
        ),
        None,
        "openai",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    llm_client, oauth_manager, provider_mode = await create_llm_client()
    app.state.llm_client = llm_client
    app.state.w3_oauth_manager = oauth_manager
    app.state.provider_mode = provider_mode
    yield


app = FastAPI(title="Claude-to-OpenAI API Proxy", version="1.0.0", lifespan=lifespan)

app.include_router(api_router)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("Claude-to-OpenAI API Proxy v1.0.0")
        print("")
        print("Usage: python src/main.py")
        print("")
        print("Required environment variables:")
        print("  OPENAI_API_KEY - Your OpenAI API key (not required when W3_OAUTH_ENABLED=true)")
        print("")
        print("Optional environment variables:")
        print("  ANTHROPIC_API_KEY - Expected Anthropic API key for client validation")
        print("                      If set, clients must provide this exact API key")
        print(
            f"  OPENAI_BASE_URL - OpenAI API base URL (default: https://api.openai.com/v1)"
        )
        print(f"  BIG_MODEL - Model for opus requests (default: gpt-4o)")
        print(f"  MIDDLE_MODEL - Model for sonnet requests (default: gpt-4o)")
        print(f"  SMALL_MODEL - Model for haiku requests (default: gpt-4o-mini)")
        print(f"  HOST - Server host (default: 0.0.0.0)")
        print(f"  PORT - Server port (default: 8082)")
        print(f"  LOG_LEVEL - Logging level (default: WARNING)")
        print(f"  MAX_TOKENS_LIMIT - Token limit (default: 4096)")
        print(f"  MIN_TOKENS_LIMIT - Minimum token limit (default: 100)")
        print(f"  REQUEST_TIMEOUT - Request timeout in seconds (default: 90)")
        print(f"  W3_OAUTH_ENABLED - Enable Huawei W3 OAuth provider mode (default: true via .env.w3)")
        print(f"  W3_TOKEN_FILE - OAuth credential cache path (default: ~/.hw_minimax_oauth.json)")
        print(f"  W3_OPEN_BROWSER - Open SSO login browser on startup (default: true on WSL)")
        print(f"  W3_VERIFY_TLS - Verify W3 TLS certificates (default: false)")
        print("")
        print("Model mapping:")
        print(f"  Claude haiku models -> {config.small_model}")
        print(f"  Claude sonnet/opus models -> {config.big_model}")
        sys.exit(0)

    # Configuration summary
    print("🚀 Claude-to-OpenAI API Proxy v1.0.0")
    print(f"✅ Configuration loaded successfully")
    print(f"   OpenAI Base URL: {config.openai_base_url}")
    print(f"   Big Model (opus): {config.big_model}")
    print(f"   Middle Model (sonnet): {config.middle_model}")
    print(f"   Small Model (haiku): {config.small_model}")
    print(f"   Max Tokens Limit: {config.max_tokens_limit}")
    print(f"   Request Timeout: {config.request_timeout}s")
    print(f"   Provider Mode: {'W3 OAuth' if config.w3_oauth_enabled else 'OpenAI-compatible'}")
    if config.w3_oauth_enabled:
        print(f"   W3 API Base URL: {config.w3_api_base_url}")
        print(f"   W3 Token File: {config.w3_token_file}")
        print(f"   W3 Open Browser: {'Enabled' if config.w3_open_browser else 'Disabled'}")
    print(f"   Server: {config.host}:{config.port}")
    print(f"   Client API Key Validation: {'Enabled' if config.anthropic_api_key else 'Disabled'}")
    print("")

    # Parse log level - extract just the first word to handle comments
    log_level = config.log_level.split()[0].lower()
    
    # Validate and set default if invalid
    valid_levels = ['debug', 'info', 'warning', 'error', 'critical']
    if log_level not in valid_levels:
        log_level = 'info'

    # Start server
    uvicorn.run(
        "src.main:app",
        host=config.host,
        port=config.port,
        log_level=log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()
