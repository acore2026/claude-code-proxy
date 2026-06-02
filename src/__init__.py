"""Claude Code Proxy

A proxy server that enables Claude Code to work with OpenAI-compatible API providers.
"""

from dotenv import load_dotenv
from pathlib import Path

# Load local overrides first; fall back to the committed W3 default env file.
if not load_dotenv():
    load_dotenv(Path(".env.w3"))

__version__ = "1.1.1"
__author__ = "Claude Code Proxy"
