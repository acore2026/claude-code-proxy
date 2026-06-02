import os
import sys
from pathlib import Path

from src.core.w3_oauth import is_wsl


def parse_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")

# Configuration
class Config:
    def __init__(self):
        self.w3_oauth_enabled = parse_bool(os.environ.get("W3_OAUTH_ENABLED"), False)
        self.w3_api_base_url = os.environ.get(
            "W3_API_BASE_URL",
            "https://codeagentcli.rnd.huawei.com/codeAgentPro",
        )
        self.w3_auth_url = os.environ.get(
            "W3_AUTH_URL",
            "https://ssoproxysvr.cd-cloud-ssoproxysvr.szv.dragon.tools.huawei.com/ssoproxysvr/oauth2/authorize",
        )
        self.w3_token_url = os.environ.get(
            "W3_TOKEN_URL",
            f"{self.w3_api_base_url}/oauth/getToken",
        )
        self.w3_refresh_url = os.environ.get(
            "W3_REFRESH_URL",
            f"{self.w3_api_base_url}/oauth/refreshToken",
        )
        self.w3_client_id = os.environ.get(
            "W3_CLIENT_ID",
            "com.huawei.devmind.codebot.apibot",
        )
        self.w3_callback_url_base = os.environ.get(
            "W3_CALLBACK_URL_BASE",
            f"{self.w3_api_base_url}/oauth/callback",
        )
        self.w3_scope = os.environ.get("W3_SCOPE", "1000:1002")
        self.w3_provider_id = os.environ.get("W3_PROVIDER_ID", "hw-minimax")
        self.w3_model = os.environ.get("W3_MODEL", "MiniMax-M2.7")
        self.w3_token_file = Path(
            os.environ.get("W3_TOKEN_FILE", "~/.hw_minimax_oauth.json")
        ).expanduser()
        self.w3_verify_tls = parse_bool(os.environ.get("W3_VERIFY_TLS"), False)
        self.w3_open_browser = parse_bool(os.environ.get("W3_OPEN_BROWSER"), is_wsl())
        self.w3_refresh_skew_seconds = int(os.environ.get("W3_REFRESH_SKEW_SECONDS", "300"))
        self.w3_auth_timeout_seconds = int(os.environ.get("W3_AUTH_TIMEOUT_SECONDS", "300"))

        self.openai_api_key = os.environ.get("OPENAI_API_KEY")
        if not self.openai_api_key and not self.w3_oauth_enabled:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        # Add Anthropic API key for client validation
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.anthropic_api_key:
            print("Warning: ANTHROPIC_API_KEY not set. Client API key validation will be disabled.")
        
        self.openai_base_url = os.environ.get(
            "OPENAI_BASE_URL",
            self.w3_api_base_url if self.w3_oauth_enabled else "https://api.openai.com/v1",
        )
        self.azure_api_version = os.environ.get("AZURE_API_VERSION")  # For Azure OpenAI
        self.host = os.environ.get("HOST", "0.0.0.0")
        self.port = int(os.environ.get("PORT", "8082"))
        self.log_level = os.environ.get("LOG_LEVEL", "INFO")
        self.max_tokens_limit = int(os.environ.get("MAX_TOKENS_LIMIT", "4096"))
        self.min_tokens_limit = int(os.environ.get("MIN_TOKENS_LIMIT", "100"))
        
        # Connection settings
        self.request_timeout = int(os.environ.get("REQUEST_TIMEOUT", "90"))
        self.max_retries = int(os.environ.get("MAX_RETRIES", "2"))
        
        # Model settings - BIG and SMALL models
        default_big_model = self.w3_model if self.w3_oauth_enabled else "gpt-4o"
        default_small_model = self.w3_model if self.w3_oauth_enabled else "gpt-4o-mini"
        self.big_model = os.environ.get("BIG_MODEL", default_big_model)
        self.middle_model = os.environ.get("MIDDLE_MODEL", self.big_model)
        self.small_model = os.environ.get("SMALL_MODEL", default_small_model)
        
    def validate_api_key(self):
        """Basic API key validation"""
        if self.w3_oauth_enabled and not self.openai_api_key:
            return True
        if not self.openai_api_key:
            return False
        # Basic format check for OpenAI API keys
        if not self.openai_api_key.startswith('sk-'):
            return False
        return True
        
    def validate_client_api_key(self, client_api_key):
        """Validate client's Anthropic API key"""
        # If no ANTHROPIC_API_KEY is set in environment, skip validation
        if not self.anthropic_api_key:
            return True
            
        # Check if the client's API key matches the expected value
        return client_api_key == self.anthropic_api_key
    
    def get_custom_headers(self):
        """Get custom headers from environment variables"""
        custom_headers = {}
        
        # Get all environment variables
        env_vars = dict(os.environ)
        
        # Find CUSTOM_HEADER_* environment variables
        for env_key, env_value in env_vars.items():
            if env_key.startswith('CUSTOM_HEADER_'):
                # Convert CUSTOM_HEADER_KEY to Header-Key
                # Remove 'CUSTOM_HEADER_' prefix and convert to header format
                header_name = env_key[14:]  # Remove 'CUSTOM_HEADER_' prefix
                
                if header_name:  # Make sure it's not empty
                    # Convert underscores to hyphens for HTTP header format
                    header_name = header_name.replace('_', '-')
                    custom_headers[header_name] = env_value
        
        return custom_headers

try:
    config = Config()
    provider_auth = "W3_OAUTH" if config.w3_oauth_enabled and not config.openai_api_key else f"API_KEY={'*' * 20}..."
    print(f"Configuration loaded: {provider_auth}, BASE_URL='{config.openai_base_url}'")
except Exception as e:
    print(f"Configuration Error: {e}")
    sys.exit(1)
