"""LLM adapters. Each plugs a concrete model into the abstract interface.

Currently registered:
  * ``mock``     -- deterministic, offline, review-safe stubs (default).
  * ``deepseek`` -- DeepSeek chat-completions adapter (the tech team's target
                    backend, "DeepSeek V4.1 Flash"). Live only with an API key.

To add a model: create ``adapters/<name>.py`` exporting an ``LLMAdapter``
subclass, then register it in :func:`ai.service.build_adapter`.
"""
from __future__ import annotations

from ai.adapters.deepseek import DeepSeekAdapter
from ai.adapters.mock import MockAdapter

__all__ = ["DeepSeekAdapter", "MockAdapter"]
