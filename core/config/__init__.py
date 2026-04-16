"""Configuration system for PQS."""

# Lazy imports avoid the runpy double-import warning when running
# `python -m core.config.loader` directly.
from __future__ import annotations


def load_config(*args, **kwargs):
    from .loader import load_config as _load
    return _load(*args, **kwargs)


def __getattr__(name: str):
    if name == "PQSConfig":
        from .loader import PQSConfig
        return PQSConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["load_config", "PQSConfig"]
