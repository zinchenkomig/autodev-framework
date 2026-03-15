"""Task queue for distributing work across agents.

Provides an async-first interface for enqueuing, claiming, and completing
development tasks. Backed by the database (and optionally Redis in future).

TODO: Implement Redis-backed queue for horizontal scaling.
TODO: Add priority queue support.
TODO: Add dead-letter queue for failed tasks.
TODO: Add task retry logic with exponential backoff.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QueuedTask:
    """A task waiting to be processed by an agent.

    TODO: Replace with proper Task ORM model reference.
    """

    task_id: str
    payload: dict[str, Any]
    priority: int = 0
    enqueued_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class TaskQueue:
    """In-memory async task queue for agent work distribution.

    This is a simple implementation suitable for single-node deployment.
    For production multi-node setups, use the Redis-backed implementation.

    TODO: Persist queue state to database on shutdown.
    TODO: Implement claim/ack protocol to avoid task loss on crash.

    Example::

        queue = TaskQueue()
        await queue.enqueue(QueuedTask(task_id="t1", payload={"action": "code"}))
        task = await queue.dequeue()
    """

    def __init__(self, maxsize: int = 0) -> None:
        """Initialize the task queue.

        Args:
            maxsize: Maximum number of tasks to hold (0 = unlimited).
        """
        self._queue: asyncio.Queue[QueuedTask] = asyncio.Queue(maxsize=maxsize)
        self._pending: deque[QueuedTask] = deque()

    async def enqueue(self, task: QueuedTask) -> None:
        """Add a task to the queue.

        Args:
            task: The task to enqueue.
        """
        logger.debug("Enqueueing task %s", task.task_id)
        await self._queue.put(task)

    async def dequeue(self, timeout: float | None = None) -> QueuedTask | None:
        """Claim the next available task.

        Args:
            timeout: Seconds to wait before returning None.

        Returns:
            The next queued task, or None on timeout.
        """
        try:
            if timeout is not None:
                return await asyncio.wait_for(self._queue.get(), timeout=timeout)
            return await self._queue.get()
        except TimeoutError:
            return None

    def complete(self, task: QueuedTask) -> None:
        """Mark a task as completed (signals queue slot freed).

        Args:
            task: The task that was completed.
        """
        self._queue.task_done()
        logger.debug("Task %s completed", task.task_id)

    def size(self) -> int:
        """Return the current number of queued tasks."""
        return self._queue.qsize()

    async def join(self) -> None:
        """Wait until all queued tasks have been completed."""
        await self._queue.join()
