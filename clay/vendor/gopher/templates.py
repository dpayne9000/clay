"""Simple ``{variable}`` prompt template substitution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def prompt_template(variables: Mapping[str, Any], template: str) -> str:
    """Substitute ``{name}`` placeholders in ``template`` with ``variables``.

    Each ``{name}`` in the template is replaced by ``variables["name"]``.
    Literal braces are escaped as ``{{`` and ``}}``.

    Example:
        >>> prompt_template({"car": "honda", "color": "red"}, "my {car} is {color}")
        'my honda is red'

    Args:
        variables: Mapping of placeholder names to their replacement values.
        template: Template string containing ``{name}`` placeholders.

    Returns:
        The template with all placeholders substituted.

    Raises:
        TypeError: If ``variables`` is not a mapping or ``template`` is not a str.
        KeyError: If the template references a name missing from ``variables``.
        ValueError: If the template contains unbalanced braces.
    """
    if not isinstance(variables, Mapping):
        raise TypeError("variables must be a mapping")
    if not isinstance(template, str):
        raise TypeError("template must be a str")

    return template.format_map(_StrictMap(variables))


class _StrictMap(dict):
    """Mapping wrapper that raises a clear ``KeyError`` for missing names."""

    def __missing__(self, key: str) -> Any:
        raise KeyError(f"template references unknown variable: {key!r}")


if __name__ == "__main__":
    print(prompt_template({"car": "honda", "color": "red"}, "my {car} is {color}"))
