from __future__ import annotations

from typing import Type

from .base import Source

_REGISTRY: dict[str, Type[Source]] = {}


def register_source(type_name: str):
    """Decorator. @register_source("newbalance") on the class."""

    def deco(cls: Type[Source]) -> Type[Source]:
        if type_name in _REGISTRY:
            raise ValueError(f"source type '{type_name}' already registered")
        _REGISTRY[type_name] = cls
        return cls

    return deco


def get_source_class(type_name: str) -> Type[Source]:
    try:
        return _REGISTRY[type_name]
    except KeyError as e:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(f"unknown source type '{type_name}'. known: {known}") from e


def all_registered() -> list[str]:
    return sorted(_REGISTRY)


# Import side-effect: register built-in sources.
# Keep at bottom to avoid circular imports.
from . import newbalance  # noqa: F401,E402
