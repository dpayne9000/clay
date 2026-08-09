"""Command-line interface for Gopher."""

from __future__ import annotations

import argparse
from typing import Optional

from .chat import chat_completion, stream_chat_completion
from .responses import extract_text, stream_text
from .template import prompt_template


def build_parser() -> argparse.ArgumentParser:
    """Create and configure the Gopher command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="gopher-chat",
        description="Send raw chat-completion requests to an OpenAI-compatible server.",
    )
    parser.add_argument("prompt", help="User prompt to send")
    parser.add_argument(
        "--endpoint",
        default="http://127.0.0.1:8080",
        help="Server root or complete /v1/chat/completions URL",
    )
    parser.add_argument("--model", default="local-model")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--system", default=None)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--stream", action="store_true")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Run the Gopher command-line client.

    Args:
        argv: Optional argument list. ``None`` uses ``sys.argv``.

    Returns:
        Process-compatible exit status. Zero indicates success.
    """
    args = build_parser().parse_args(argv)

    messages = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": args.prompt})

    if args.stream:
        chunks = stream_chat_completion(
            args.endpoint,
            messages,
            model=args.model,
            api_key=args.api_key,
            timeout=args.timeout,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        for fragment in stream_text(chunks):
            print(fragment, end="", flush=True)
        print()
        return 0

    response = chat_completion(
        args.endpoint,
        messages,
        model=args.model,
        api_key=args.api_key,
        timeout=args.timeout,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    print(extract_text(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
