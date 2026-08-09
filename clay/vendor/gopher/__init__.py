"""Gopher public API.

Gopher is a dependency-free client for raw OpenAI-compatible chat-completion
requests, including llama.cpp llama-server.
"""

from .chat import chat_completion, stream_chat_completion
from .errors import (
    GopherAPIError,
    GopherConnectionError,
    GopherHTTPError,
    GopherResponseError,
    GopherTimeoutError,
)
from .fewshot import build_messages
from .responses import extract_text, stream_text
from .urls import normalize_chat_url

__all__ = [
    "GopherAPIError",
    "GopherConnectionError",
    "GopherHTTPError",
    "GopherResponseError",
    "GopherTimeoutError",
    "build_messages",
    "chat_completion",
    "extract_text",
    "normalize_chat_url",
    "stream_chat_completion",
    "stream_text",
]

__version__ = "1.0.0"
