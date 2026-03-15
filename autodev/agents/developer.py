"""Developer agent — writes and refactors code.

Receives coding tasks from the queue, interacts with the GitHub integration
to create branches and pull requests, and uses the browser agent for
research when needed.

TODO: Implement code generation via LLM provider.
TODO: Integrate with GitHub integration for PR creation.
TODO: Add code review self-check before opening PR.
TODO: Implement branch naming convention enforcement.
"""

from __future__ import annotations

import logging

from autodev.core.events import DomainEvent
from autodev.core.queue import QueuedTask
from autodev.core.runner import BaseAgent

logger = logging.getLogger(__name__)


class DeveloperAgent(BaseAgent):
    """Autonomous developer agent.

    Processes coding tasks: feature implementation, bug fixes, refactoring.

    TODO: Add LLM client injection.
    TODO: Add file system access via sandboxed workspace.
    """

    role = "developer"

    async def run(self, task: QueuedTask) -> None:
        """Execute a coding task.

        Args:
            task: Task with payload describing the work to perform.

        TODO: Parse task payload to determine action type.
        TODO: Invoke LLM to generate code changes.
        TODO: Create PR via GitHub integration.
        """
        logger.info("[developer] Processing task %s: %s", task.task_id, task.payload)
        # TODO: Implement actual development workflow

    async def handle_event(self, event: DomainEvent) -> None:
        """React to domain events relevant to the developer role.

        TODO: Handle ``task.assigned`` events.
        TODO: Handle ``review.requested`` events to self-review PRs.
        """
        logger.debug("[developer] Event received: %s", event.event_type)
