"""AgentRunner protocol and base implementation.

Defines the interface all agents must implement, and provides a base class
with lifecycle hooks and error handling boilerplate.

TODO: Add resource limits (CPU, memory, API rate limits) per runner.
TODO: Integrate with StateManager to publish agent heartbeats.
TODO: Add support for cancellation and graceful shutdown.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from typing import Protocol, runtime_checkable

from autodev.core.events import DomainEvent, EventBus
from autodev.core.queue import QueuedTask, TaskQueue

logger = logging.getLogger(__name__)


@runtime_checkable
class AgentRunner(Protocol):
    """Protocol that every agent must satisfy.

    Agents implement ``run`` to process tasks from the queue and
    ``handle_event`` to react to domain events.
    """

    async def run(self, task: QueuedTask) -> None:
        """Process a single task.

        Args:
            task: The task claimed from the queue.
        """
        ...

    async def handle_event(self, event: DomainEvent) -> None:
        """React to a domain event published on the event bus.

        Args:
            event: The event to handle.
        """
        ...


class BaseAgent:
    """Abstract base class providing agent lifecycle scaffolding.

    Subclass this and implement ``run`` (and optionally ``handle_event``)
    to create a concrete agent.

    TODO: Add retry logic in ``_run_loop``.
    TODO: Add metrics collection (tasks processed, errors, latency).

    Example::

        class MyAgent(BaseAgent):
            async def run(self, task: QueuedTask) -> None:
                print(f"Processing {task.task_id}")
    """

    #: Role label used in logs and state keys.
    role: str = "base"

    def __init__(self, queue: TaskQueue, event_bus: EventBus) -> None:
        """Initialise the agent.

        Args:
            queue: Shared task queue to pull work from.
            event_bus: Shared event bus for publishing / subscribing.
        """
        self.queue = queue
        self.event_bus = event_bus
        self._running = False

    async def start(self) -> None:
        """Start the agent's main processing loop."""
        logger.info("%s agent starting", self.role)
        self._running = True
        await self._run_loop()

    async def stop(self) -> None:
        """Signal the agent to stop after finishing current task."""
        logger.info("%s agent stopping", self.role)
        self._running = False

    async def _run_loop(self) -> None:
        """Internal loop: dequeue and process tasks until stopped.

        TODO: Configurable dequeue timeout.
        TODO: Backoff on repeated errors.
        """
        while self._running:
            task = await self.queue.dequeue(timeout=1.0)
            if task is None:
                continue
            try:
                await self.run(task)
            except Exception:
                logger.exception("%s agent failed on task %s", self.role, task.task_id)
            finally:
                self.queue.complete(task)

    @abstractmethod
    async def run(self, task: QueuedTask) -> None:
        """Process a single task. Must be implemented by subclasses."""
        raise NotImplementedError

    async def handle_event(self, event: DomainEvent) -> None:
        """Default no-op event handler. Override in subclasses as needed."""
        logger.debug("%s ignoring event %s", self.role, event.event_type)
