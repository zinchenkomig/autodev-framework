"""State manager for tracking global framework and agent state.

Provides a centralised, thread-safe store for runtime state that needs to
be shared across agents and API handlers within a single process.

TODO: Replace in-memory store with Redis for multi-process deployments.
TODO: Add state change notifications via EventBus.
TODO: Add snapshot / restore for crash recovery.
"""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from typing import Any

logger = logging.getLogger(__name__)

# Sentinel used to detect missing keys without conflicting with None values.
_MISSING = object()


class StateManager:
    """Thread-safe async key-value state store.

    Keys are dot-separated namespaces, e.g. ``"agents.developer.status"``.

    Example::

        state = StateManager()
        await state.set("system.phase", "running")
        phase = await state.get("system.phase")
    """

    def __init__(self) -> None:
        """Initialise with an empty state dict and a reentrant lock."""
        self._store: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def set(self, key: str, value: Any) -> None:
        """Set a state value.

        Args:
            key: Dot-namespaced state key.
            value: Value to store (deep-copied for safety).
        """
        async with self._lock:
            self._store[key] = deepcopy(value)
            logger.debug("State set: %s = %r", key, value)

    async def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a state value.

        Args:
            key: Dot-namespaced state key.
            default: Returned when key is absent.

        Returns:
            Deep copy of stored value, or *default*.
        """
        async with self._lock:
            value = self._store.get(key, _MISSING)
            if value is _MISSING:
                return default
            return deepcopy(value)

    async def delete(self, key: str) -> bool:
        """Remove a key from the store.

        Args:
            key: Key to remove.

        Returns:
            True if the key existed and was removed.
        """
        async with self._lock:
            existed = key in self._store
            self._store.pop(key, None)
            return existed

    async def keys(self, prefix: str = "") -> list[str]:
        """Return all keys, optionally filtered by prefix.

        Args:
            prefix: Only return keys starting with this string.

        Returns:
            Sorted list of matching keys.
        """
        async with self._lock:
            return sorted(k for k in self._store if k.startswith(prefix))

    async def snapshot(self) -> dict[str, Any]:
        """Return a full deep copy of the current state.

        TODO: Serialise to JSON and persist for crash recovery.
        """
        async with self._lock:
            return deepcopy(self._store)
