"""Few-shot example normalization and message construction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional


def build_messages(
    messages: list[dict[str, Any]],
    *,
    fewshot_examples: Optional[list[Any]] = None,
) -> list[dict[str, Any]]:
    """Create a new message list containing normalized few-shot examples.

    Leading ``system`` and ``developer`` messages remain at the beginning.
    Normalized examples are inserted immediately after those instructions and
    before the active conversation.

    Supported example formats are:

    - ``("user input", "assistant output")``
    - ``{"user": ..., "assistant": ...}``
    - ``{"input": ..., "output": ...}``
    - ``{"prompt": ..., "completion": ...}``
    - Raw ``{"role": ..., "content": ...}`` message dictionaries

    Args:
        messages: Active OpenAI-compatible conversation messages.
        fewshot_examples: Optional examples to insert into the conversation.

    Returns:
        A new list. The input list and its message dictionaries are not
        modified.

    Raises:
        TypeError: If messages or examples have unsupported types.
        ValueError: If an example mapping is incomplete or has an unsupported
            role.
    """
    if not isinstance(messages, list):
        raise TypeError("messages must be a list")

    copied_messages = [_copy_message(message, index) for index, message in enumerate(messages)]
    if not fewshot_examples:
        return copied_messages

    if not isinstance(fewshot_examples, list):
        raise TypeError("fewshot_examples must be a list or None")

    normalized: list[dict[str, Any]] = []
    for index, example in enumerate(fewshot_examples):
        normalized.extend(_normalize_example(example, index))

    insertion_index = 0
    while insertion_index < len(copied_messages):
        if copied_messages[insertion_index].get("role") not in {"system", "developer"}:
            break
        insertion_index += 1

    return (
        copied_messages[:insertion_index]
        + normalized
        + copied_messages[insertion_index:]
    )


def _copy_message(message: Any, index: int) -> dict[str, Any]:
    """Validate and shallow-copy one conversation message."""
    if not isinstance(message, Mapping):
        raise TypeError(f"messages[{index}] must be a mapping")
    return dict(message)


def _normalize_example(example: Any, index: int) -> list[dict[str, Any]]:
    """Normalize one supported few-shot representation into message objects."""
    if isinstance(example, Mapping):
        if "role" in example and "content" in example:
            role = str(example["role"])
            allowed = {"system", "developer", "user", "assistant", "tool"}
            if role not in allowed:
                raise ValueError(
                    f"fewshot_examples[{index}] has unsupported role: {role}"
                )
            return [dict(example)]

        key_pairs = (
            ("user", "assistant"),
            ("input", "output"),
            ("prompt", "completion"),
            ("question", "answer"),
        )
        for user_key, assistant_key in key_pairs:
            if user_key in example and assistant_key in example:
                return [
                    {"role": "user", "content": example[user_key]},
                    {"role": "assistant", "content": example[assistant_key]},
                ]

        raise ValueError(
            f"fewshot_examples[{index}] must contain user/assistant, "
            "input/output, prompt/completion, or role/content"
        )

    if isinstance(example, (list, tuple)) and len(example) == 2:
        return [
            {"role": "user", "content": example[0]},
            {"role": "assistant", "content": example[1]},
        ]

    raise TypeError(
        f"fewshot_examples[{index}] must be a two-item pair or mapping"
    )
